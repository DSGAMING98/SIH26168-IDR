package org.sih26168.idrlogger.engine

import java.util.ArrayDeque
import kotlin.math.hypot
import kotlin.math.max
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.RuntimeGnssFix

data class IdrEngineConfig(
    val maximumDtS: Double = 0.5,
    val recoveryVerificationFixes: Int = 2,
    val recoveryCorrectionRateMps: Double = 5.0,
    val recoveryMinimumSamples: Int = 15,
    val recoveryCompletionDistanceM: Double = 5.0,
    val recoveryFreshTimeoutS: Double = 3.0,
    val maximumTrajectoryPoints: Int = 2_000,
    val maximumTrustedGnssAccuracyM: Double = 35.0,
    val maximumUncorrectedSpeedMps: Double = 40.0,
    val maximumUncorrectedSpeedIncreaseMps: Double = 15.0,
    val minimumUncorrectedSpeedCeilingMps: Double = 25.0,
)

private data class TrustedGnss(
    val fix: RuntimeGnssFix,
    val solutionTimestampNs: Long,
)

/** Standalone, causal live IDR engine. Its only external sample input is the Phase 9 runtime object. */
class IdrEngine(
    private val config: IdrEngineConfig = IdrEngineConfig(),
    private val conditioner: SensorConditioner = SensorConditioner(),
    private val alignment: VehicleAlignment = VehicleAlignment(),
    private val ekf: ClassicalEkf = ClassicalEkf(),
    private val mlVelocity: CausalMlVelocity = CausalMlVelocity(),
) {
    private var transform: CoordinateTransform? = null
    private var lastTimestampNs: Long? = null
    private var lastGnssSolutionTimestampNs: Long? = null
    private var lastFreshReceivedNs: Long? = null
    private var lossStartedNs: Long? = null
    private var verificationFixes = 0
    private var recoverySamples = 0
    private var recoveryTarget: LocalPoint? = null
    private var lastTrustedSpeedMps: Double? = null
    private var mode = LocalizationMode.WAITING_FOR_GNSS
    private var latest = NavigationState()
    private val trajectory = ArrayDeque<TrajectoryPoint>()
    private val processingTimesMs = ArrayDeque<Double>()
    private val inertialStopGate = InertialStopGate()

    @Synchronized
    fun reset() {
        transform = null
        lastTimestampNs = null
        lastGnssSolutionTimestampNs = null
        lastFreshReceivedNs = null
        lossStartedNs = null
        verificationFixes = 0
        recoverySamples = 0
        recoveryTarget = null
        lastTrustedSpeedMps = null
        mode = LocalizationMode.WAITING_FOR_GNSS
        latest = NavigationState()
        trajectory.clear()
        processingTimesMs.clear()
        conditioner.reset()
        alignment.reset()
        ekf.reset()
        mlVelocity.reset()
        inertialStopGate.reset()
    }

    @Synchronized
    fun process(sample: LiveIdrSample): NavigationState {
        val processingStarted = System.nanoTime()
        require(sample.monotonicTimestampNs > 0L) { "Runtime sample timestamp must be positive." }
        // Validate the blackout boundary even when this sample is dropped for timing. A timing
        // discontinuity must never become a way to bypass the GNSS leakage guard.
        val trustedGnss = trustedRuntimeGnss(sample)
        val previousTimestamp = lastTimestampNs
        val dtS = if (previousTimestamp == null) 0.1 else {
            (sample.monotonicTimestampNs - previousTimestamp) / 1e9
        }
        if (previousTimestamp != null && (!dtS.isFinite() || dtS <= 0.0 || dtS > config.maximumDtS)) {
            return handleTimingDiscontinuity(sample, dtS, trustedGnss != null, processingStarted)
        }
        val distinctGnss = trustedGnss?.takeIf { it.solutionTimestampNs > (lastGnssSolutionTimestampNs ?: Long.MIN_VALUE) }
        if (distinctGnss != null) {
            lastGnssSolutionTimestampNs = distinctGnss.solutionTimestampNs
            lastFreshReceivedNs = sample.monotonicTimestampNs
            distinctGnss.fix.speedMps?.takeIf { it.isFinite() && it >= 0.0 }?.let { lastTrustedSpeedMps = it }
        }

        val initializedBeforeSample = ekf.initialized
        if (!initializedBeforeSample && distinctGnss != null) initialize(distinctGnss.fix)
        val yawForConditioning = if (ekf.initialized) ekf.yawRad else distinctGnss?.fix?.bearingDeg?.let(Math::toRadians) ?: 0.0
        val conditioned = conditioner.condition(sample, dtS, yawForConditioning)
        if (distinctGnss != null) {
            alignment.update(
                conditioned.deviceHeadingRad,
                distinctGnss.fix.bearingDeg,
                distinctGnss.fix.speedMps,
            )
        } else if (conditioned.deviceHeadingRad == null && alignment.state != AlignmentState.READY) {
            alignment.update(null, null, null)
        }

        var innovationM: Double? = null
        var correctionM = 0.0
        if (ekf.initialized) {
            if (initializedBeforeSample) {
                if (alignment.state == AlignmentState.READY) {
                    ekf.predict(dtS, conditioned.forwardAccelerationMps2, conditioned.yawRateRadps)
                } else {
                    ekf.holdForMissingAlignment(dtS)
                }
            }
            val alignmentHeading = alignment.vehicleHeading(conditioned.deviceHeadingRad)
            if (alignmentHeading != null) ekf.updateYaw(alignmentHeading, Math.toRadians(20.0))
            if (trustedGnss == null) {
                val speedCeiling = max(
                    config.minimumUncorrectedSpeedCeilingMps,
                    (lastTrustedSpeedMps ?: 0.0) + config.maximumUncorrectedSpeedIncreaseMps,
                ).coerceAtMost(config.maximumUncorrectedSpeedMps)
                ekf.constrainSpeed(speedCeiling)
            }
            val inertialStopConfirmed = inertialStopGate.update(dtS, conditioned)
            val confidentlyStationary = inertialStopConfirmed || (conditioned.motionState == MotionState.LIKELY_STATIONARY &&
                ekf.speedMps < STATIONARY_SPEED_GATE_MPS && (trustedGnss?.fix?.speedMps ?: 0.0) < STATIONARY_SPEED_GATE_MPS
            )
            if (confidentlyStationary) ekf.applyStationaryConstraint()

            val (mlState, inference) = if (alignment.state == AlignmentState.READY) {
                mlVelocity.update(buildMlFeatures(conditioned, confidentlyStationary))
            } else {
                mlVelocity.reset()
                MlRuntimeState.ML_UNAVAILABLE to null
            }
            if (inference != null && mlVelocity.inferenceUpdated && alignment.state == AlignmentState.READY && !confidentlyStationary) {
                when (mlState) {
                    MlRuntimeState.ML_ACCEPTED -> ekf.applyMlSpeedMeasurement(
                        ekf.speedMps + inference.residualMps,
                        FrozenVelocityModelData.VALIDATION_RESIDUAL_VARIANCE_MPS2,
                    )
                    MlRuntimeState.ML_OOD_LIMITED -> ekf.applyMlSpeedMeasurement(
                        ekf.speedMps + inference.residualMps,
                        FrozenVelocityModelData.VALIDATION_RESIDUAL_VARIANCE_MPS2 * 4.0,
                    )
                    else -> Unit
                }
            }
            if (trustedGnss == null) {
                val speedCeiling = max(
                    config.minimumUncorrectedSpeedCeilingMps,
                    (lastTrustedSpeedMps ?: 0.0) + config.maximumUncorrectedSpeedIncreaseMps,
                ).coerceAtMost(config.maximumUncorrectedSpeedMps)
                ekf.constrainSpeed(speedCeiling)
            }

            val suppressStationaryTranslation = confidentlyStationary ||
                (conditioned.motionState != MotionState.MOVING &&
                    ekf.speedMps < STATIONARY_SPEED_GATE_MPS &&
                    (trustedGnss?.fix?.speedMps ?: 0.0) < STATIONARY_SPEED_GATE_MPS)
            val gnssResult = updateGnssState(
                sample,
                distinctGnss,
                trustedGnss != null,
                dtS,
                suppressStationaryTranslation,
            )
            innovationM = gnssResult.first
            correctionM = gnssResult.second
            check(ekf.isFinite()) { "IDR state or covariance became non-finite." }
            latest = buildNavigationState(
                sample,
                conditioned,
                confidentlyStationary,
                mlState,
                inference,
                innovationM,
                correctionM,
            )
            appendTrajectory(latest)
        } else {
            mode = when (sample.gnssStatus) {
                GnssStatus.WAITING_FOR_FIRST_FIX -> LocalizationMode.WAITING_FOR_GNSS
                GnssStatus.PROVIDER_DISABLED, GnssStatus.INVALID -> LocalizationMode.GNSS_DEGRADED
                else -> LocalizationMode.WAITING_FOR_GNSS
            }
            latest = NavigationState(
                sequenceId = sample.sequenceId,
                monotonicTimestampNs = sample.monotonicTimestampNs,
                localizationMode = mode,
                alignmentState = alignment.state,
                alignmentProgress = alignment.progress,
                motionState = conditioned.motionState,
                mlState = MlRuntimeState.ML_WARMING,
                message = modeMessage(mode),
            )
        }
        lastTimestampNs = sample.monotonicTimestampNs
        val processingMs = (System.nanoTime() - processingStarted) / 1e6
        processingTimesMs.addLast(processingMs)
        while (processingTimesMs.size > PERFORMANCE_WINDOW) processingTimesMs.removeFirst()
        latest = latest.copy(
            engineAverageMs = processingTimesMs.average(),
            engineP95Ms = percentile(processingTimesMs, 0.95),
        )
        return latest
    }

    /**
     * Drops a sample separated from the previous normalized tick by an unsupported interval.
     * No conditioner, EKF, recovery correction, ML inference, or trajectory append is executed.
     * The current timestamp becomes the new baseline so the following normal tick can resume.
     */
    private fun handleTimingDiscontinuity(
        sample: LiveIdrSample,
        dtS: Double,
        trustedGnssAvailable: Boolean,
        processingStarted: Long,
    ): NavigationState {
        lastTimestampNs = sample.monotonicTimestampNs
        conditioner.reset()
        mlVelocity.reset()
        inertialStopGate.reset()
        verificationFixes = 0
        recoverySamples = 0
        recoveryTarget = null
        lossStartedNs = null
        mode = when {
            mode == LocalizationMode.ERROR -> LocalizationMode.ERROR
            !ekf.initialized -> LocalizationMode.WAITING_FOR_GNSS
            trustedGnssAvailable && alignment.state == AlignmentState.READY -> LocalizationMode.GNSS_ACTIVE
            trustedGnssAvailable -> LocalizationMode.CALIBRATING
            alignment.state == AlignmentState.READY -> LocalizationMode.GNSS_DEGRADED
            else -> LocalizationMode.CALIBRATION_REQUIRED
        }
        val gapLabel = if (dtS.isFinite()) "${"%.3f".format(java.util.Locale.US, dtS)} s" else "non-finite"
        val discontinuityMessage = "Stream timing discontinuity ($gapLabel); sample dropped and timing reset"
        latest = latest.copy(
            sequenceId = sample.sequenceId,
            monotonicTimestampNs = sample.monotonicTimestampNs,
            localizationMode = mode,
            alignmentState = alignment.state,
            alignmentProgress = alignment.progress,
            mlState = MlRuntimeState.ML_WARMING,
            mlResidualMps = null,
            mlOodExceedance = null,
            drDurationSeconds = 0.0,
            gnssInnovationM = null,
            lastCorrectionM = 0.0,
            message = if (mode == LocalizationMode.ERROR) latest.message else discontinuityMessage,
        )
        val processingMs = (System.nanoTime() - processingStarted) / 1e6
        processingTimesMs.addLast(processingMs)
        while (processingTimesMs.size > PERFORMANCE_WINDOW) processingTimesMs.removeFirst()
        latest = latest.copy(
            engineAverageMs = processingTimesMs.average(),
            engineP95Ms = percentile(processingTimesMs, 0.95),
        )
        return latest
    }

    @Synchronized
    fun snapshot(isDemoReplay: Boolean = false): NavigationSnapshot = NavigationSnapshot(
        state = latest,
        trajectory = trajectory.toList(),
        isDemoReplay = isDemoReplay,
    )

    @Synchronized
    fun reportFailure(message: String, timestampNs: Long): NavigationState {
        mode = LocalizationMode.ERROR
        latest = latest.copy(
            monotonicTimestampNs = timestampNs,
            localizationMode = mode,
            message = "Localization error: $message",
        )
        return latest
    }

    private fun initialize(fix: RuntimeGnssFix) {
        transform = CoordinateTransform(fix.latitudeDeg, fix.longitudeDeg)
        val yaw = Math.toRadians(fix.bearingDeg ?: 0.0)
        ekf.initialize(fix.speedMps ?: 0.0, yaw, fix.accuracyM ?: 8.0)
        mode = LocalizationMode.CALIBRATING
    }

    private fun trustedRuntimeGnss(sample: LiveIdrSample): TrustedGnss? {
        if (sample.simulatedBlackout || sample.gnssStatus == GnssStatus.SIMULATED_BLACKOUT) {
            require(sample.gnss == null && !sample.gnssIsFresh) {
                "GNSS leakage: simulated blackout carried a runtime GNSS fix."
            }
            return null
        }
        if (sample.gnssStatus != GnssStatus.FRESH || !sample.gnssIsFresh) return null
        val fix = sample.gnss ?: return null
        if (!fix.latitudeDeg.isFinite() || !fix.longitudeDeg.isFinite() ||
            fix.latitudeDeg !in -90.0..90.0 || fix.longitudeDeg !in -180.0..180.0 ||
            fix.accuracyM?.let { !it.isFinite() || it <= 0.0 || it > config.maximumTrustedGnssAccuracyM } == true
        ) return null
        val ageNs = ((sample.gnssFixAgeSeconds ?: 0.0).coerceAtLeast(0.0) * 1e9).toLong()
        val solutionTimestampNs = sample.gnssDiagnostics.lastPhysicalGnssTimestampNs
            ?: (sample.monotonicTimestampNs - ageNs)
        return TrustedGnss(fix, solutionTimestampNs)
    }

    private fun updateGnssState(
        sample: LiveIdrSample,
        distinctGnss: TrustedGnss?,
        trustedGnssAvailable: Boolean,
        dtS: Double,
        suppressStationaryTranslation: Boolean,
    ): Pair<Double?, Double> {
        val local = distinctGnss?.fix?.let { transform!!.toLocal(it.latitudeDeg, it.longitudeDeg) }
        val hasRecentFreshFix = lastFreshReceivedNs?.let {
            (sample.monotonicTimestampNs - it) / 1e9 <= config.recoveryFreshTimeoutS
        } ?: false
        if (mode == LocalizationMode.GNSS_RECOVERING && recoveryTarget != null && hasRecentFreshFix) {
            if (local != null) recoveryTarget = local
            val target = recoveryTarget!!
            val innovation = ekf.innovationTo(target.eastM, target.northM)
            val correction = ekf.nudgePositionToward(
                target.eastM,
                target.northM,
                config.recoveryCorrectionRateMps * dtS,
            )
            distinctGnss?.fix?.speedMps?.let { ekf.updateSpeed(it, 2.0) }
            distinctGnss?.fix?.bearingDeg?.let { ekf.updateYaw(Math.toRadians(it), Math.toRadians(20.0)) }
            recoverySamples += 1
            val completionDistanceM = if (suppressStationaryTranslation) {
                minOf(config.recoveryCompletionDistanceM, STATIONARY_RECOVERY_DISTANCE_M)
            } else config.recoveryCompletionDistanceM
            if (recoverySamples >= config.recoveryMinimumSamples && innovation <= completionDistanceM) {
                mode = if (alignment.state == AlignmentState.READY) LocalizationMode.GNSS_ACTIVE else LocalizationMode.CALIBRATING
                lossStartedNs = null
                verificationFixes = 0
                recoveryTarget = null
            }
            return innovation to correction
        }
        if (mode == LocalizationMode.GNSS_VERIFYING && distinctGnss != null) {
            verificationFixes += 1
            if (verificationFixes >= config.recoveryVerificationFixes) {
                recoveryTarget = local
                recoverySamples = 0
                mode = LocalizationMode.GNSS_RECOVERING
                val target = requireNotNull(local)
                val innovation = ekf.innovationTo(target.eastM, target.northM)
                val correction = ekf.nudgePositionToward(
                    target.eastM,
                    target.northM,
                    config.recoveryCorrectionRateMps * dtS,
                )
                return innovation to correction
            }
            return local?.let { ekf.innovationTo(it.eastM, it.northM) } to 0.0
        }
        if (mode == LocalizationMode.GNSS_VERIFYING && !hasRecentFreshFix) {
            enterIdr(sample.monotonicTimestampNs)
            return null to 0.0
        }
        val lossMode = mode == LocalizationMode.IDR_ACTIVE || mode == LocalizationMode.GNSS_DEGRADED ||
            mode == LocalizationMode.CALIBRATION_REQUIRED
        if (lossMode && distinctGnss != null) {
            verificationFixes = 1
            mode = LocalizationMode.GNSS_VERIFYING
            return local?.let { ekf.innovationTo(it.eastM, it.northM) } to 0.0
        }
        if (distinctGnss != null && local != null) {
            val innovation = ekf.innovationTo(local.eastM, local.northM)
            // A stationary receiver's successive GNSS fixes describe measurement scatter, not
            // travelled distance. Keep the initialized/last-moving anchor until independent
            // motion evidence appears; the raw callback remains fully observable in the logger.
            if (!suppressStationaryTranslation) {
                ekf.updatePosition(local.eastM, local.northM, distinctGnss.fix.accuracyM ?: 8.0)
            }
            distinctGnss.fix.speedMps?.let { ekf.updateSpeed(it) }
            if (!suppressStationaryTranslation) {
                distinctGnss.fix.bearingDeg?.let { ekf.updateYaw(Math.toRadians(it)) }
            }
            mode = if (alignment.state == AlignmentState.READY) LocalizationMode.GNSS_ACTIVE else LocalizationMode.CALIBRATING
            lossStartedNs = null
            return innovation to 0.0
        }
        if (trustedGnssAvailable && mode != LocalizationMode.GNSS_VERIFYING && mode != LocalizationMode.GNSS_RECOVERING) {
            mode = if (alignment.state == AlignmentState.READY) LocalizationMode.GNSS_ACTIVE else LocalizationMode.CALIBRATING
            lossStartedNs = null
            return null to 0.0
        }
        if (mode == LocalizationMode.GNSS_RECOVERING && !hasRecentFreshFix) {
            enterIdr(sample.monotonicTimestampNs)
        } else if (mode != LocalizationMode.GNSS_VERIFYING && mode != LocalizationMode.GNSS_RECOVERING) {
            enterIdr(sample.monotonicTimestampNs)
        }
        return null to 0.0
    }

    private fun enterIdr(timestampNs: Long) {
        if (lossStartedNs == null) lossStartedNs = timestampNs
        mode = if (alignment.state == AlignmentState.READY) LocalizationMode.IDR_ACTIVE else LocalizationMode.CALIBRATION_REQUIRED
        verificationFixes = 0
        recoverySamples = 0
        recoveryTarget = null
    }

    private fun buildMlFeatures(conditioned: ConditionedMotion, stationary: Boolean) = doubleArrayOf(
        conditioned.forwardAccelerationMps2,
        conditioned.leftAccelerationMps2,
        conditioned.yawRateRadps,
        conditioned.gyroMagnitudeRadps,
        conditioned.gravityMagnitudeMps2,
        conditioned.magneticMagnitudeUt,
        conditioned.accelerationRmsMps2,
        conditioned.gyroRmsRadps,
        if (stationary) 1.0 else 0.0,
        ekf.speedMps,
    )

    private fun buildNavigationState(
        sample: LiveIdrSample,
        conditioned: ConditionedMotion,
        stationary: Boolean,
        mlState: MlRuntimeState,
        inference: MlInference?,
        innovationM: Double?,
        correctionM: Double,
    ): NavigationState {
        val geodetic = transform!!.toGeodetic(ekf.eastM, ekf.northM)
        val sigma = ekf.horizontalSigmaM
        val drDuration = lossStartedNs?.let { max(0.0, (sample.monotonicTimestampNs - it) / 1e9) } ?: 0.0
        val confidence = when {
            mode == LocalizationMode.WAITING_FOR_GNSS -> ConfidenceLevel.UNAVAILABLE
            mode == LocalizationMode.CALIBRATION_REQUIRED || mode == LocalizationMode.GNSS_DEGRADED -> ConfidenceLevel.LOW
            sigma < 10.0 -> ConfidenceLevel.HIGH
            sigma < 35.0 -> ConfidenceLevel.MEDIUM
            else -> ConfidenceLevel.LOW
        }
        return NavigationState(
            sequenceId = sample.sequenceId,
            monotonicTimestampNs = sample.monotonicTimestampNs,
            latitudeDeg = geodetic.latitudeDeg,
            longitudeDeg = geodetic.longitudeDeg,
            eastM = ekf.eastM,
            northM = ekf.northM,
            speedMps = ekf.speedMps,
            headingDeg = headingRadToDegrees(ekf.yawRad),
            horizontalUncertaintyM = sigma,
            confidence = confidence,
            localizationMode = mode,
            alignmentState = alignment.state,
            alignmentProgress = alignment.progress,
            motionState = if (stationary) MotionState.LIKELY_STATIONARY else conditioned.motionState,
            mlState = mlState,
            mlResidualMps = inference?.residualMps,
            mlOodExceedance = inference?.oodExceedance,
            drDurationSeconds = drDuration,
            gnssInnovationM = innovationM,
            lastCorrectionM = correctionM,
            message = if (stationary && mode == LocalizationMode.IDR_ACTIVE) {
                "IDR active · vehicle stationary — position held using stationary constraint"
            } else modeMessage(mode),
        )
    }

    private fun appendTrajectory(state: NavigationState) {
        // Calibration is not navigation and must never create a convincing-looking route from
        // indoor GNSS scatter. History begins only once vehicle alignment is ready.
        if (state.localizationMode == LocalizationMode.CALIBRATING ||
            state.localizationMode == LocalizationMode.WAITING_FOR_GNSS ||
            state.localizationMode == LocalizationMode.CALIBRATION_REQUIRED ||
            state.localizationMode == LocalizationMode.GNSS_DEGRADED
        ) return
        val previous = trajectory.peekLast()
        if (previous == null || hypot(state.eastM - previous.eastM, state.northM - previous.northM) >= 0.10 ||
            previous.localizationMode != state.localizationMode
        ) {
            trajectory.addLast(TrajectoryPoint(state.eastM, state.northM, state.localizationMode))
            while (trajectory.size > config.maximumTrajectoryPoints) trajectory.removeFirst()
        }
    }

    private fun modeMessage(value: LocalizationMode): String = when (value) {
        LocalizationMode.WAITING_FOR_GNSS -> "Waiting for first trusted GNSS fix"
        LocalizationMode.CALIBRATING -> "Calibrating phone-to-vehicle alignment"
        LocalizationMode.CALIBRATION_REQUIRED -> "Position held — vehicle direction calibration required"
        LocalizationMode.GNSS_ACTIVE -> "GNSS active"
        LocalizationMode.GNSS_DEGRADED -> "GNSS degraded; alignment incomplete"
        LocalizationMode.IDR_ACTIVE -> "Intelligent dead reckoning active"
        LocalizationMode.GNSS_VERIFYING -> "GNSS returned; verifying fixes"
        LocalizationMode.GNSS_RECOVERING -> "GNSS verified; reconciling smoothly"
        LocalizationMode.ERROR -> "Localization unavailable"
    }

    private fun percentile(values: Collection<Double>, fraction: Double): Double {
        if (values.isEmpty()) return 0.0
        val sorted = values.sorted()
        val index = ((sorted.size - 1) * fraction).toInt().coerceIn(sorted.indices)
        return sorted[index]
    }

    companion object {
        private const val STATIONARY_SPEED_GATE_MPS = 0.8
        private const val STATIONARY_RECOVERY_DISTANCE_M = 0.5
        private const val PERFORMANCE_WINDOW = 200
    }
}
