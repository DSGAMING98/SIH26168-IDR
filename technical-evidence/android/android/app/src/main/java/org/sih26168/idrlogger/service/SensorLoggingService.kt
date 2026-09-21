package org.sih26168.idrlogger.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import java.io.File
import java.util.concurrent.CopyOnWriteArraySet
import org.sih26168.idrlogger.R
import org.sih26168.idrlogger.core.CausalSensorBuffer
import org.sih26168.idrlogger.core.GnssFreshnessTracker
import org.sih26168.idrlogger.core.GnssLocationRepository
import org.sih26168.idrlogger.core.IdrSampleObserver
import org.sih26168.idrlogger.core.IdrSensorStream
import org.sih26168.idrlogger.core.SensorRateTracker
import org.sih26168.idrlogger.core.SensorRepository
import org.sih26168.idrlogger.core.TimestampNormalizer
import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.IdrEngine
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.field.FieldTestController
import org.sih26168.idrlogger.field.FieldTestEvent
import org.sih26168.idrlogger.logging.Phase11SessionSummary
import org.sih26168.idrlogger.logging.SessionLogger
import org.sih26168.idrlogger.model.FieldTestPhase
import org.sih26168.idrlogger.model.FieldTestPreset
import org.sih26168.idrlogger.model.FieldTestStatus
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.LoggerStatus
import org.sih26168.idrlogger.model.MountProfile
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.SensorKind
import org.sih26168.idrlogger.model.Vector3
import org.sih26168.idrlogger.product.NavGhostDatabase
import org.sih26168.idrlogger.product.RoomTripStore
import org.sih26168.idrlogger.product.TripRecorder
import org.sih26168.idrlogger.system.SystemHealthMonitor
import org.sih26168.idrlogger.ui.MainActivity
import org.sih26168.idrlogger.telemetry.TelemetryClient
import org.sih26168.idrlogger.telemetry.TelemetryConfig
import org.sih26168.idrlogger.telemetry.TelemetryDiagnostics
import org.sih26168.idrlogger.telemetry.TelemetryMapMode
import org.sih26168.idrlogger.telemetry.TelemetrySettings
import org.sih26168.idrlogger.telemetry.TelemetryStatus

class SensorLoggingService : Service(), IdrSensorStream {
    inner class LocalBinder : Binder() {
        fun service(): SensorLoggingService = this@SensorLoggingService
    }

    private val binder = LocalBinder()
    private val observers = CopyOnWriteArraySet<IdrSampleObserver>()
    private val buffer = CausalSensorBuffer()
    private val freshnessTracker = GnssFreshnessTracker()
    private val rateTracker = SensorRateTracker()
    private val idrEngine = IdrEngine()
    private val fieldTestController = FieldTestController()
    private var sensorRepository: SensorRepository? = null
    private var gnssRepository: GnssLocationRepository? = null
    private var logger: SessionLogger? = null
    private var normalizer: TimestampNormalizer? = null
    private var snapshotThread: HandlerThread? = null
    private var snapshotHandler: Handler? = null
    private var snapshotRunnable: Runnable? = null
    private var originNs = 0L
    private var sequenceId = 0L
    @Volatile private var manualBlackout = false
    @Volatile private var fieldTestStatus = FieldTestStatus()
    @Volatile private var currentStatus = LoggerStatus()
    @Volatile private var tunnelGateRejection: String? = null
    private lateinit var systemHealthMonitor: SystemHealthMonitor
    private var initialSystemHealth = org.sih26168.idrlogger.model.SystemHealthSnapshot()
    private var currentSystemHealth = org.sih26168.idrlogger.model.SystemHealthSnapshot()
    private var runtimeSampleCount = 0L
    private val mlStateCounts = mutableMapOf<String, Long>()
    private var loggerErrorCount = 0
    private var telemetryClient: TelemetryClient? = null
    private var telemetrySessionId: String? = null
    @Volatile private var telemetryMapMode = TelemetryMapMode.LOCAL_ENU
    @Volatile private var productRendererLabel = "AUTO"
    private lateinit var tripRecorder: TripRecorder

    override fun onCreate() {
        super.onCreate()
        systemHealthMonitor = SystemHealthMonitor(this)
        tripRecorder = TripRecorder(RoomTripStore(NavGhostDatabase.get(this).tripDao())).also { it.recoverInterruptedTrips() }
        createNotificationChannel()
        // Observer startup failure must never become a navigation/service startup failure.
        telemetryClient = runCatching {
            TelemetryClient().also { it.configure(TelemetrySettings(this).load()) }
        }.getOrNull()
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> start()
            ACTION_STOP -> {
                stop()
                stopSelf()
            }
            ACTION_TOGGLE_BLACKOUT -> setSimulatedBlackout(intent.getBooleanExtra(EXTRA_BLACKOUT, false))
        }
        return START_NOT_STICKY
    }

    override fun start() {
        if (currentStatus.recording) return
        try {
            startForeground(NOTIFICATION_ID, buildNotification())
            originNs = SystemClock.elapsedRealtimeNanos()
            val startWallMs = System.currentTimeMillis()
            normalizer = TimestampNormalizer(originNs, startWallMs)
            sequenceId = 0L
            manualBlackout = false
            fieldTestController.reset()
            fieldTestStatus = FieldTestStatus()
            runtimeSampleCount = 0L
            mlStateCounts.clear()
            loggerErrorCount = 0
            tunnelGateRejection = null
            initialSystemHealth = systemHealthMonitor.snapshot(foregroundServiceActive = true, loggerErrorCount = 0)
            currentSystemHealth = initialSystemHealth
            buffer.clear()
            rateTracker.reset()
            freshnessTracker.reset(originNs)
            idrEngine.reset()
            telemetrySessionId = runCatching { telemetryClient?.startSession() }.getOrNull()

            sensorRepository = SensorRepository(
                this,
                buffer,
                rateTracker,
                onRawSample = { sample ->
                    normalizer?.let { time ->
                        logger?.logSensor(
                            sample,
                            time.elapsedSeconds(sample.monotonicTimestampNs),
                            time.wallClockUtc(sample.monotonicTimestampNs),
                        )
                    }
                },
                onError = { message ->
                    loggerErrorCount += 1
                    logger?.logEvent("SENSOR_WARNING", message)
                    currentStatus = currentStatus.copy(message = message)
                },
            )
            gnssRepository = GnssLocationRepository(
                this,
                freshnessTracker,
                isSimulatedBlackout = { isBlackoutActive() },
                onPhysicalFix = { fix, status, masked ->
                    logger?.logPhysicalGnss(fix, normalizer!!.elapsedSeconds(fix.monotonicTimestampNs), status, masked)
                },
                onEvent = { type, message -> logger?.logEvent(type, message) },
            )
            val availability = sensorRepository!!.availability(gnssRepository!!.gpsProviderAvailable)
            logger = SessionLogger(
                this,
                originNs,
                startWallMs,
                SensorRepository.REQUESTED_SAMPLING_PERIOD_US,
                NORMALIZED_RATE_HZ,
                sensorRepository!!.sensorInfo,
                availability,
                android.location.LocationManager.GPS_PROVIDER,
                initialSystemHealth,
            )
            currentStatus = LoggerStatus(
                recording = true,
                availability = availability,
                sessionDirectory = logger!!.sessionDirectory.absolutePath,
                message = readinessMessage(availability),
                systemHealth = currentSystemHealth,
                fieldTest = fieldTestStatus,
            )
            tripRecorder.start(startWallMs, logger!!.sessionDirectory.absolutePath, productRendererLabel)
            sensorRepository!!.start()
            if (!gnssRepository!!.start()) currentStatus = currentStatus.copy(message = "GNSS LOST OR PERMISSION DENIED")
            startSnapshotLoop(availability)
        } catch (error: Exception) {
            if (::tripRecorder.isInitialized) tripRecorder.stop(System.currentTimeMillis(), interrupted = true)
            runCatching { telemetryClient?.stopSession() }
            snapshotRunnable?.let { snapshotHandler?.removeCallbacks(it) }
            snapshotThread?.quitSafely()
            gnssRepository?.stop()
            sensorRepository?.stop()
            logger?.close(
                System.currentTimeMillis(),
                rateTracker.snapshot(),
                freshnessTracker.diagnostics(SystemClock.elapsedRealtimeNanos(), isBlackoutActive()),
                phase11Summary(foregroundServiceActive = false),
            )
            snapshotRunnable = null
            snapshotHandler = null
            snapshotThread = null
            gnssRepository = null
            sensorRepository = null
            logger = null
            currentStatus = currentStatus.copy(recording = false, message = "LOGGER ERROR: ${error.message}")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    override fun stop() {
        if (!currentStatus.recording) return
        runCatching { telemetryClient?.stopSession() }
        snapshotRunnable?.let { snapshotHandler?.removeCallbacks(it) }
        snapshotRunnable = null
        snapshotThread?.quitSafely()
        snapshotThread = null
        snapshotHandler = null
        gnssRepository?.stop()
        sensorRepository?.stop()
        val nowNs = SystemClock.elapsedRealtimeNanos()
        tripRecorder.stop(System.currentTimeMillis())
        cancelFieldTestInternal(nowNs)
        val finalGnssDiagnostics = freshnessTracker.diagnostics(nowNs, isBlackoutActive())
        logger?.close(
            System.currentTimeMillis(),
            rateTracker.snapshot(),
            finalGnssDiagnostics,
            phase11Summary(foregroundServiceActive = false),
        )
        val lastDirectory = logger?.sessionDirectory?.absolutePath
        logger = null
        tunnelGateRejection = null
        sensorRepository = null
        gnssRepository = null
        currentStatus = currentStatus.copy(
            recording = false,
            rates = rateTracker.snapshot(),
            gnssDiagnostics = finalGnssDiagnostics,
            sessionDirectory = lastDirectory,
            message = "STOPPED — files flushed",
            systemHealth = currentSystemHealth,
            fieldTest = fieldTestStatus,
        )
        // A stopped session must not keep presenting its final coordinate as a live position.
        // The completed trip has already been persisted above.
        idrEngine.reset()
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    override fun addObserver(observer: IdrSampleObserver) {
        observers.add(observer)
    }

    override fun removeObserver(observer: IdrSampleObserver) {
        observers.remove(observer)
    }

    fun status(): LoggerStatus = currentStatus

    fun navigationSnapshot(): NavigationSnapshot = idrEngine.snapshot(isDemoReplay = false)

    fun telemetryStatus(): TelemetryStatus = telemetryClient?.status() ?: TelemetryStatus()
    fun telemetryConfiguration(): TelemetryConfig = telemetryClient?.configuration() ?: TelemetryConfig()
    fun configureTelemetry(config: TelemetryConfig): String? {
        config.normalized().validationError()?.let { return it }
        if (config.enabled) {
            val uri = java.net.URI(config.endpoint.trim())
            if (uri.scheme == "ws" && !android.security.NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted(uri.host)) {
                return "This APK does not trust that cleartext host. Build with -PNAVGHOST_LAN_HOST=<LAPTOP_IPV4>, or use trusted wss://."
            }
        }
        val client = telemetryClient ?: return "Telemetry unavailable; navigation is unaffected"
        client.configure(config)?.let { return it }
        TelemetrySettings(this).save(config)
        return null
    }
    fun connectTelemetry() { telemetryClient?.connect() }
    fun disconnectTelemetry() { telemetryClient?.disconnect() }
    fun setTelemetryMapMode(googleMapsActive: Boolean) {
        telemetryMapMode = if (googleMapsActive) TelemetryMapMode.GOOGLE_MAPS else TelemetryMapMode.LOCAL_ENU
    }
    fun setProductRendererLabel(label: String) { productRendererLabel = label.take(40) }

    fun setSimulatedBlackout(enabled: Boolean): TunnelTestEligibility {
        if (fieldTestStatus.phase !in setOf(
                FieldTestPhase.IDLE,
                FieldTestPhase.COMPLETE,
                FieldTestPhase.CANCELLED,
            )
        ) {
            currentStatus = currentStatus.copy(message = "AUTOMATIC FIELD TEST CONTROLS GNSS LOSS")
            return TunnelTestEligibility(false, currentStatus.message)
        }
        if (enabled) {
            val eligibility = tunnelTestEligibility(SystemClock.elapsedRealtimeNanos())
            if (!eligibility.allowed) {
                manualBlackout = false
                tunnelGateRejection = eligibility.message
                currentStatus = currentStatus.copy(simulatedBlackout = false, message = eligibility.message)
                logger?.logEvent("SIMULATED_BLACKOUT_REJECTED", eligibility.message)
                return eligibility
            }
        }
        tunnelGateRejection = null
        manualBlackout = enabled
        val nowNs = SystemClock.elapsedRealtimeNanos()
        val effectiveBlackout = isBlackoutActive()
        val trackerDiagnostics = freshnessTracker.diagnostics(nowNs, effectiveBlackout)
        val diagnostics = trackerDiagnostics.copy(
            blackoutMasksRealFix = currentStatus.recording && trackerDiagnostics.blackoutMasksRealFix,
        )
        logger?.logEvent(
            if (enabled) "SIMULATED_BLACKOUT_STARTED" else "SIMULATED_BLACKOUT_STOPPED",
            when {
                !enabled -> "Runtime GNSS visibility restored."
                diagnostics.blackoutMasksFreshFix -> "A currently fresh physical GNSS fix is masked from runtime."
                diagnostics.hasAcquiredRealFixThisSession ->
                    "A real fix existed earlier, but no currently fresh physical fix is being masked."
                else -> "Development blackout enabled before any valid physical fix; no real fix is being masked."
            },
        )
        val state = freshnessTracker.runtimeState(nowNs, effectiveBlackout)
        currentStatus = currentStatus.copy(
            simulatedBlackout = effectiveBlackout,
            gnssStatus = state.status,
            gnssDiagnostics = diagnostics,
            message = gnssMessage(state.status, diagnostics, currentStatus.availability),
        )
        return TunnelTestEligibility(true, currentStatus.message)
    }

    fun startFieldTest(preset: FieldTestPreset, mountProfile: MountProfile): Boolean {
        if (!currentStatus.recording) {
            currentStatus = currentStatus.copy(message = "START LIVE RECORDING BEFORE FIELD TEST")
            return false
        }
        val nowNs = SystemClock.elapsedRealtimeNanos()
        manualBlackout = false
        val testId = "${logger?.sessionDirectory?.name ?: "session"}_${preset.name}_${nowNs}"
        val update = synchronized(fieldTestController) {
            fieldTestController.start(nowNs, testId, preset, mountProfile)
        }
        applyFieldTestUpdate(update.status, update.events, nowNs)
        return true
    }

    fun cancelFieldTest() {
        cancelFieldTestInternal(SystemClock.elapsedRealtimeNanos())
    }

    fun latestSessionDirectory(): File? {
        currentStatus.sessionDirectory?.let { path -> File(path).takeIf(File::isDirectory)?.let { return it } }
        return File(filesDir, "recordings").listFiles()?.filter(File::isDirectory)?.maxByOrNull(File::lastModified)
    }

    override fun onDestroy() {
        stop()
        telemetryClient?.shutdown()
        super.onDestroy()
    }

    private fun startSnapshotLoop(availability: SensorAvailability) {
        val producerSessionId = telemetrySessionId
        snapshotThread = HandlerThread("IdrNormalized10Hz").also { it.start() }
        snapshotHandler = Handler(snapshotThread!!.looper)
        snapshotRunnable = object : Runnable {
            override fun run() {
                if (!currentStatus.recording) return
                val timestampNs = SystemClock.elapsedRealtimeNanos()
                val time = normalizer ?: return
                val unmaskedGnss = freshnessTracker.runtimeState(timestampNs, false)
                val fieldUpdate = synchronized(fieldTestController) {
                    fieldTestController.update(
                        timestampNs,
                        idrEngine.snapshot().state.alignmentState == AlignmentState.READY,
                        unmaskedGnss.status == GnssStatus.FRESH && unmaskedGnss.runtimeFix != null,
                    )
                }
                applyFieldTestUpdate(fieldUpdate.status, fieldUpdate.events, timestampNs)
                val effectiveBlackout = isBlackoutActive()
                val gnssState = freshnessTracker.runtimeState(timestampNs, effectiveBlackout)
                val gnssDiagnostics = freshnessTracker.diagnostics(timestampNs, effectiveBlackout)
                val sample = LiveIdrSample(
                    sequenceId = sequenceId++,
                    elapsedSeconds = time.elapsedSeconds(timestampNs),
                    monotonicTimestampNs = timestampNs,
                    wallClockUtc = time.wallClockUtc(timestampNs),
                    accelerometer = vectorAt(SensorKind.ACCELEROMETER, timestampNs),
                    gyroscope = vectorAt(SensorKind.GYROSCOPE, timestampNs),
                    magnetometer = vectorAt(SensorKind.MAGNETOMETER, timestampNs),
                    gravity = vectorAt(SensorKind.GRAVITY, timestampNs),
                    rotation = quaternionAt(timestampNs),
                    gnss = gnssState.runtimeFix,
                    gnssFixAgeSeconds = gnssState.ageSeconds,
                    gnssIsFresh = gnssState.isFresh,
                    gnssStatus = gnssState.status,
                    simulatedBlackout = effectiveBlackout,
                    gnssDiagnostics = gnssDiagnostics,
                    availability = availability,
                )
                rateTracker.recordNormalized(timestampNs)
                logger?.logRuntime(sample)
                val navigation = try {
                    idrEngine.process(sample)
                } catch (error: Exception) {
                    loggerErrorCount += 1
                    logger?.logEvent("IDR_ENGINE_ERROR", error.message ?: error.javaClass.simpleName)
                    idrEngine.reportFailure(error.message ?: error.javaClass.simpleName, timestampNs)
                }
                if (navigation.message.startsWith("Stream timing discontinuity")) {
                    logger?.logEvent("RUNTIME_TIMING_DISCONTINUITY", navigation.message)
                }
                if (tunnelGateRejection != null && TunnelTestGate.evaluate(
                        recording = true,
                        freshPhysicalGnssAvailable = unmaskedGnss.status == GnssStatus.FRESH && unmaskedGnss.runtimeFix != null,
                        navigation = navigation,
                    ).allowed
                ) {
                    tunnelGateRejection = null
                }
                runtimeSampleCount += 1L
                mlStateCounts[navigation.mlState.name] = (mlStateCounts[navigation.mlState.name] ?: 0L) + 1L
                if (runtimeSampleCount % SYSTEM_HEALTH_SAMPLE_INTERVAL == 0L) {
                    currentSystemHealth = systemHealthMonitor.snapshot(true, loggerErrorCount)
                }
                logger?.logNavigation(sample, navigation)
                tripRecorder.record(navigation, System.currentTimeMillis())
                observers.forEach { it.onSample(sample) }
                val g = sample.gnss
                currentStatus = LoggerStatus(
                    recording = true,
                    elapsedSeconds = sample.elapsedSeconds,
                    gnssStatus = sample.gnssStatus,
                    gnssAgeSeconds = sample.gnssFixAgeSeconds,
                    latitudeDeg = g?.latitudeDeg,
                    longitudeDeg = g?.longitudeDeg,
                    speedMps = g?.speedMps,
                    bearingDeg = g?.bearingDeg,
                    simulatedBlackout = sample.simulatedBlackout,
                    gnssDiagnostics = sample.gnssDiagnostics,
                    availability = availability,
                    rates = rateTracker.snapshot(),
                    sessionDirectory = logger?.sessionDirectory?.absolutePath,
                    message = tunnelGateRejection ?: gnssMessage(sample.gnssStatus, sample.gnssDiagnostics, availability),
                    systemHealth = currentSystemHealth,
                    fieldTest = fieldTestStatus,
                )
                // Completed estimator output only. Neither sample.gnss nor LoggerStatus is passed.
                // publish is one atomic latest-slot replacement; JSON/network run on a separate worker.
                runCatching {
                    telemetryClient?.publish(navigation, TelemetryDiagnostics(
                        wallTimeUtc = sample.wallClockUtc,
                        gnssStatus = sample.gnssStatus,
                        gnss = sample.gnssDiagnostics,
                        rates = currentStatus.rates,
                        health = currentSystemHealth,
                        fieldTestPhase = fieldTestStatus.phase,
                        mapMode = telemetryMapMode,
                        recording = true,
                    ), producerSessionId)
                }
                snapshotHandler?.postDelayed(this, NORMALIZED_PERIOD_MS)
            }
        }
        snapshotHandler!!.post(snapshotRunnable!!)
    }

    private fun vectorAt(kind: SensorKind, timestampNs: Long): Vector3? {
        val values = buffer.latestAtOrBefore(kind, timestampNs)?.values ?: return null
        if (values.size < 3) return null
        return Vector3(values[0], values[1], values[2])
    }

    private fun quaternionAt(timestampNs: Long): Quaternion? {
        val values = buffer.latestAtOrBefore(SensorKind.ROTATION_VECTOR, timestampNs)?.values ?: return null
        if (values.size < 4) return null
        return Quaternion(values[0], values[1], values[2], values[3])
    }

    private fun applyFieldTestUpdate(status: FieldTestStatus, events: List<FieldTestEvent>, nowNs: Long) {
        fieldTestStatus = status
        if (events.isNotEmpty()) {
            logger?.updateFieldTestStatus(status)
            val elapsed = normalizer?.elapsedSeconds(nowNs) ?: 0.0
            events.forEach { event ->
                logger?.logFieldTestEvent(event.type, event.message, nowNs, elapsed, event.status)
            }
        }
        currentStatus = currentStatus.copy(fieldTest = status, simulatedBlackout = isBlackoutActive())
    }

    private fun cancelFieldTestInternal(nowNs: Long) {
        val update = synchronized(fieldTestController) { fieldTestController.cancel(nowNs) }
        applyFieldTestUpdate(update.status, update.events, nowNs)
        manualBlackout = false
    }

    private fun isBlackoutActive(): Boolean = manualBlackout || fieldTestStatus.blackoutActive

    private fun tunnelTestEligibility(nowNs: Long): TunnelTestEligibility {
        val physicalGnss = freshnessTracker.runtimeState(nowNs, false)
        return TunnelTestGate.evaluate(
            recording = currentStatus.recording,
            freshPhysicalGnssAvailable = physicalGnss.status == GnssStatus.FRESH && physicalGnss.runtimeFix != null,
            navigation = idrEngine.snapshot().state,
        )
    }

    private fun phase11Summary(foregroundServiceActive: Boolean): Phase11SessionSummary {
        currentSystemHealth = systemHealthMonitor.snapshot(foregroundServiceActive, loggerErrorCount)
        val engine = idrEngine.snapshot().state
        return Phase11SessionSummary(
            runtimeSampleCount = runtimeSampleCount,
            mlStateCounts = mlStateCounts.toMap(),
            engineAverageMs = engine.engineAverageMs,
            engineP95Ms = engine.engineP95Ms,
            finalLocalizationState = engine.localizationMode.name,
            finalAlignmentState = engine.alignmentState.name,
            finalMotionState = engine.motionState.name,
            startSystemHealth = initialSystemHealth,
            endSystemHealth = currentSystemHealth,
        )
    }

    private fun readinessMessage(availability: SensorAvailability): String = when {
        !availability.accelerometer || !availability.gyroscope -> "SENSOR MISSING — core IMU incomplete"
        !availability.magnetometer || !availability.gravity -> "SENSORS READY — optional sensor missing"
        else -> "SENSORS READY"
    }

    private fun gnssMessage(
        status: GnssStatus,
        diagnostics: GnssDiagnosticsSnapshot,
        availability: SensorAvailability,
    ): String = when (status) {
        GnssStatus.WAITING_FOR_FIRST_FIX -> "WAITING FOR FIRST GNSS FIX"
        GnssStatus.FRESH -> "GNSS ACTIVE"
        GnssStatus.STALE -> "GNSS STALE"
        GnssStatus.INVALID -> "GNSS INVALID"
        GnssStatus.PROVIDER_DISABLED -> "GNSS PROVIDER DISABLED"
        GnssStatus.SIMULATED_BLACKOUT -> if (diagnostics.blackoutMasksFreshFix) {
            "SIMULATED GNSS BLACKOUT — FRESH PHYSICAL FIX MASKED"
        } else if (diagnostics.hasAcquiredRealFixThisSession) {
            "SIMULATED GNSS BLACKOUT — ONLY HISTORICAL FIX AVAILABLE"
        } else {
            "SIMULATED GNSS BLACKOUT — NO REAL FIX TO MASK"
        }
    }.let { message ->
        if (!availability.accelerometer || !availability.gyroscope) "$message — CORE IMU MISSING" else message
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = getString(R.string.notification_channel_description) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val mainIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, SensorLoggingService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_navghost_notification)
            .setContentTitle("NavGhost navigation active")
            .setContentText("On-device sensors and localization are running")
            .setContentIntent(mainIntent)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop", stopIntent).build())
            .build()
    }

    companion object {
        const val ACTION_START = "org.sih26168.idrlogger.START"
        const val ACTION_STOP = "org.sih26168.idrlogger.STOP"
        const val ACTION_TOGGLE_BLACKOUT = "org.sih26168.idrlogger.BLACKOUT"
        const val EXTRA_BLACKOUT = "blackout"
        private const val CHANNEL_ID = "idr_sensor_recording"
        private const val NOTIFICATION_ID = 26168
        private const val NORMALIZED_RATE_HZ = 10.0
        private const val NORMALIZED_PERIOD_MS = 100L
        private const val SYSTEM_HEALTH_SAMPLE_INTERVAL = 50L
    }
}
