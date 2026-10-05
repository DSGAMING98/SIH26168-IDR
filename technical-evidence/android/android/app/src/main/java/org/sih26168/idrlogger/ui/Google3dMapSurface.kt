package org.sih26168.idrlogger.ui

import android.content.Context
import android.graphics.Color
import android.os.SystemClock
import android.os.Handler
import android.os.Looper
import android.graphics.Typeface
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.gms.maps3d.GoogleMap3D
import com.google.android.gms.maps3d.Map3DView
import com.google.android.gms.maps3d.OnMap3DViewReadyCallback
import com.google.android.gms.maps3d.model.AltitudeMode
import com.google.android.gms.maps3d.model.Camera
import com.google.android.gms.maps3d.model.CollisionBehavior
import com.google.android.gms.maps3d.model.LatLngAltitude
import com.google.android.gms.maps3d.model.ImageView
import com.google.android.gms.maps3d.model.Map3DMode
import com.google.android.gms.maps3d.model.Marker
import com.google.android.gms.maps3d.model.MarkerOptions
import com.google.android.gms.maps3d.model.Polyline
import com.google.android.gms.maps3d.model.PolylineOptions
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.R
import org.sih26168.idrlogger.map.EngineMarkerPolicy
import org.sih26168.idrlogger.map.Google3dCameraCommandGate
import org.sih26168.idrlogger.map.Google3dCameraSanityGate
import org.sih26168.idrlogger.map.Google3dCameraVisualState
import org.sih26168.idrlogger.map.CameraSanityAction
import org.sih26168.idrlogger.map.Google3dOverlayGate
import org.sih26168.idrlogger.map.FollowGestureGate
import org.sih26168.idrlogger.map.Google3dVisualTrajectory
import org.sih26168.idrlogger.map.LatestValueSlot
import org.sih26168.idrlogger.map.MapAvailability
import org.sih26168.idrlogger.map.MapCoordinateProjector
import org.sih26168.idrlogger.map.MapPresentation
import org.sih26168.idrlogger.map.MapStateStyle
import org.sih26168.idrlogger.map.Maps3dFailurePolicy
import org.sih26168.idrlogger.map.True3dUncertaintyPolicy
import org.sih26168.idrlogger.map.True3dCameraPolicy
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.map.RendererLifecycleGate
import org.sih26168.idrlogger.map.RendererLifecycleState

/**
 * Google Maps 3D is a presentation adapter only. It receives immutable engine snapshots and has
 * no location-provider, blue-dot, route-snapping, or estimator feedback path.
 */
class Google3dMapSurface(
    context: Context,
    @Map3DMode initialMapMode: Int = Map3DMode.HYBRID,
    private val onStatus: (MapPresentation) -> Unit = {},
) : FrameLayout(context), OnMap3DViewReadyCallback {
    private val mainHandler = Handler(Looper.getMainLooper())
    // Avoid 0.2.2's broken Kotlin create$default ABI by calling its concrete public constructor.
    private val mapView = Map3DView(context, initialMapMode)
    private val waitingOverlay = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        isClickable = true
        setPadding(dp(28), dp(28), dp(28), dp(28))
        setBackgroundColor(Color.rgb(5, 13, 22))
        addView(TextView(context).apply {
            text = "WAITING FOR PRECISE POSITION"
            textSize = 18f
            setTextColor(Color.rgb(66, 224, 201))
            gravity = Gravity.CENTER
            setTypeface(typeface, Typeface.BOLD)
        })
        addView(TextView(context).apply {
            text = "Google 3D will open at the first trusted NavGhost fix."
            textSize = 13f
            setTextColor(Color.rgb(190, 207, 220))
            gravity = Gravity.CENTER
            setPadding(0, dp(8), 0, 0)
        })
    }
    private val previousUncaughtHandler = Thread.getDefaultUncaughtExceptionHandler()
    private val maps3dUncaughtHandler = Thread.UncaughtExceptionHandler { thread, error ->
        if (Maps3dFailurePolicy.isRecoverableAuthenticationFailure(error)) {
            failSession("AUTHENTICATION REJECTED")
        } else {
            previousUncaughtHandler?.uncaughtException(thread, error) ?: error.printStackTrace()
        }
    }
    private var map: GoogleMap3D? = null
    private var marker: Marker? = null
    private var trajectory: Polyline? = null
    private var uncertainty: Polyline? = null
    private var lastSnapshot = NavigationSnapshot()
    private val latestSnapshot = LatestValueSlot<NavigationSnapshot>()
    private var renderScheduled = false
    private var lastVisualDispatchMs = Long.MIN_VALUE
    private var following = true
    private val cameraPolicy = True3dCameraPolicy(CAMERA_INTERVAL_MS)
    private val cameraCommandGate = Google3dCameraCommandGate()
    private val cameraSanityGate = Google3dCameraSanityGate()
    private var lastRequestedCamera: Google3dCameraVisualState? = null
    private val overlayGate = Google3dOverlayGate()
    private val followGestureGate = FollowGestureGate(ViewConfiguration.get(context).scaledTouchSlop.toFloat())
    private val lifecycle = RendererLifecycleGate()
    private var presentation = loadingPresentation()
    private var requestedMapMode = initialMapMode
    private val performanceStartMs = SystemClock.elapsedRealtime()
    private var renderedSnapshots = 0L
    private var markerUpdates = 0L
    private var cameraCommands = 0L
    private var trajectoryUpdates = 0L
    private var uncertaintyUpdates = 0L
    private var latestOfferedSnapshotAgeMs: Double? = null
    private var latestRenderedSnapshotAgeMs: Double? = null
    private var lastRenderCompletedMs = Long.MIN_VALUE
    private var cameraToEstimatorDistanceM: Double? = null
    private var initialCameraPrimed = false
    private val hybridFallback = Runnable {
        if (lifecycle.state == RendererLifecycleState.INITIALIZING && requestedMapMode == Map3DMode.HYBRID) {
            requestedMapMode = Map3DMode.ROADMAP
            map?.setMapMode(Map3DMode.ROADMAP)
            publish(MapPresentation(PROVIDER_ID, MapAvailability.INITIALIZING, "GOOGLE 3D LOADING", "HYBRID TILES SLOW • TRYING ROADMAP", ATTRIBUTION))
        }
    }
    private val renderLatest = Runnable {
        renderScheduled = false
        val snapshot = latestSnapshot.takeLatest() ?: return@Runnable
        if (lifecycle.state == RendererLifecycleState.READY) {
            lastVisualDispatchMs = SystemClock.elapsedRealtime()
            render(snapshot)
        }
        if (latestSnapshot.hasValue()) scheduleLatestRender()
    }

    init {
        check(Looper.myLooper() == Looper.getMainLooper()) { "Google3dMapSurface must be created on the main thread" }
        check(lifecycle.begin())
        Thread.setDefaultUncaughtExceptionHandler(maps3dUncaughtHandler)
        addView(mapView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        addView(waitingOverlay, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        // The Maps 3D dynamite module can change across Play Services updates. Restoring its
        // opaque Parcelable from an older module crashed Android 16 with BadParcelableException.
        // Camera/follow state is reconstructed from the next engine snapshot instead.
        mapView.onCreate(null)
        mapView.getMap3DViewAsync(this)
    }

    /**
     * Observe gestures before Map3DView's native rendering surface consumes them.  Returning the
     * normal dispatch result preserves every Google 3D pan/zoom/tilt gesture; NavGhost only uses
     * the observation to suspend automatic camera follow until RECENTER is tapped.
     */
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> followGestureGate.onDown(event.x, event.y)
            MotionEvent.ACTION_POINTER_DOWN -> if (followGestureGate.onAdditionalPointer()) pauseFollowForGesture()
            MotionEvent.ACTION_MOVE -> if (followGestureGate.onMove(event.x, event.y)) pauseFollowForGesture()
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> followGestureGate.onEnd()
        }
        return super.dispatchTouchEvent(event)
    }

    private fun pauseFollowForGesture() {
        following = false
        cameraSanityGate.reset()
        cameraPolicy.onUserGesture()
        publish(readyPresentation("FOLLOW PAUSED • TAP RECENTER"))
    }

    override fun onMap3DViewReady(googleMap3D: GoogleMap3D) {
        mainHandler.post {
            if (lifecycle.state != RendererLifecycleState.INITIALIZING) return@post
            map = googleMap3D
            googleMap3D.setMapMode(requestedMapMode)
            googleMap3D.setOnMapSteadyListener { steady ->
                if (steady) mainHandler.post { validateCamera(googleMap3D) }
            }
            primeCamera(googleMap3D, lastSnapshot)
            mainHandler.postDelayed(hybridFallback, HYBRID_FALLBACK_MS)
            googleMap3D.setOnMapReadyListener { sceneReadiness ->
                mainHandler.post ready@{
                    if (!sceneIsReady(sceneReadiness)) {
                        val percentage = (sceneReadiness.coerceIn(0.0, 1.0) * 100.0).toInt()
                        publish(MapPresentation(PROVIDER_ID, MapAvailability.INITIALIZING, "GOOGLE 3D LOADING", "$percentage% • ENGINE ESTIMATE ONLY", ATTRIBUTION))
                        return@ready
                    }
                    if (!lifecycle.markReady()) return@ready
                    mainHandler.removeCallbacks(hybridFallback)
                    publish(readyPresentation())
                    latestSnapshot.clear()
                    lastVisualDispatchMs = SystemClock.elapsedRealtime()
                    render(lastSnapshot, forceCamera = true)
                }
            }
        }
    }

    override fun onError(error: Exception) {
        // SDK authentication callbacks may arrive on native worker threads. Serialize failure on
        // the UI thread and make it terminal for this surface; retries require a new Activity.
        mainHandler.post {
            if (!lifecycle.markFailed()) return@post
            mainHandler.removeCallbacks(hybridFallback)
            map = null
            publish(MapPresentation(PROVIDER_ID, MapAvailability.NETWORK_UNAVAILABLE, "GOOGLE 3D UNAVAILABLE", error.javaClass.simpleName, ATTRIBUTION))
        }
    }

    /** End an initialization that exceeded the owning surface's bounded startup window. */
    fun failSession(detail: String) {
        mainHandler.post {
            if (!lifecycle.markFailed()) return@post
            mainHandler.removeCallbacks(hybridFallback)
            map = null
            publish(MapPresentation(PROVIDER_ID, MapAvailability.NETWORK_UNAVAILABLE, "GOOGLE 3D UNAVAILABLE", detail, ATTRIBUTION))
        }
    }

    fun show(snapshot: NavigationSnapshot) {
        lastSnapshot = snapshot
        latestOfferedSnapshotAgeMs = monotonicAgeMs(snapshot.state.monotonicTimestampNs)
        map?.takeIf { lifecycle.state == RendererLifecycleState.INITIALIZING }?.let { primeCamera(it, snapshot) }
        latestSnapshot.offer(snapshot)
        scheduleLatestRender()
    }

    private fun primeCamera(googleMap: GoogleMap3D, snapshot: NavigationSnapshot) {
        if (initialCameraPrimed) return
        val engineMarker = EngineMarkerPolicy.from(snapshot)
        val lat = engineMarker.latitudeDeg ?: return
        val lon = engineMarker.longitudeDeg ?: return
        if (!lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0) return
        val initial = Google3dCameraVisualState(
            lat,
            lon,
            engineMarker.headingDeg.takeIf(Double::isFinite) ?: 0.0,
            58.0,
            180.0,
        )
        lastRequestedCamera = initial
        googleMap.setCamera(initial.toCamera())
        initialCameraPrimed = true
    }

    private fun scheduleLatestRender() {
        if (renderScheduled || lifecycle.state != RendererLifecycleState.READY) return
        val now = SystemClock.elapsedRealtime()
        val delay = if (lastVisualDispatchMs == Long.MIN_VALUE) 0L else
            (VISUAL_INTERVAL_MS - (now - lastVisualDispatchMs)).coerceAtLeast(0L)
        renderScheduled = true
        mainHandler.postDelayed(renderLatest, delay)
    }

    private fun render(snapshot: NavigationSnapshot, forceCamera: Boolean = false) {
        val googleMap = map ?: return
        renderedSnapshots += 1
        latestRenderedSnapshotAgeMs = monotonicAgeMs(snapshot.state.monotonicTimestampNs)
        val engineMarker = EngineMarkerPolicy.from(snapshot)
        val lat = engineMarker.latitudeDeg
        val lon = engineMarker.longitudeDeg
        if (lat == null || lon == null || !lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0) {
            clearLivePosition()
            waitingOverlay.visibility = View.VISIBLE
            return
        }
        // Lift the billboard slightly above the photorealistic mesh. Together with
        // isDrawnWhenOccluded this prevents ground/mesh z-fighting from hiding the vehicle.
        val position = LatLngAltitude(lat, lon, 5.0)
        val firstPosition = marker == null
        marker = marker ?: googleMap.addMarker(MarkerOptions().apply {
            id = "navghost_engine_estimate"
            label = null
            altitudeMode = AltitudeMode.RELATIVE_TO_MESH
            collisionBehavior = CollisionBehavior.REQUIRED_AND_HIDES_OPTIONAL
            collisionPriority = 100
            isSizePreserved = true
            isDrawnWhenOccluded = true
            zIndex = 20
            // Maps 3D ImageView accepts a packaged PNG, not an Android vector XML drawable.
            setStyle(ImageView(R.drawable.navghost_vehicle_arrow_3d))
            setPosition(position)
        })
        marker?.setPosition(position)
        markerUpdates += 1
        val now = SystemClock.elapsedRealtime()
        val trajectorySignature = trajectorySignature(snapshot)
        if (overlayGate.shouldUpdateTrajectory(now, trajectorySignature, forceCamera)) {
            updateTrajectory(googleMap, snapshot, lat, lon)
            trajectoryUpdates += 1
        }
        if (overlayGate.shouldUpdateUncertainty(
                now,
                lat,
                lon,
                snapshot.state.horizontalUncertaintyM,
                snapshot.state.localizationMode,
                forceCamera,
            )
        ) {
            updateUncertainty(googleMap, snapshot, lat, lon)
            uncertaintyUpdates += 1
        }
        val forceFollow = forceCamera || firstPosition
        if (following && (forceFollow || cameraPolicy.shouldUpdate(now))) {
            val frame = cameraPolicy.frame(
                engineMarker,
                snapshot.state.speedMps,
                snapshot.state.motionState,
                snapshot.state.localizationMode,
                snapshot.state.confidence == ConfidenceLevel.HIGH || snapshot.state.confidence == ConfidenceLevel.MEDIUM,
            ) ?: return
            val rangeM = (210.0 - (frame.zoom - 16.65) * 72.0).coerceIn(95.0, 210.0)
            val visualState = Google3dCameraVisualState(
                frame.target.latitudeDeg,
                frame.target.longitudeDeg,
                frame.bearingDeg,
                frame.pitchDeg,
                rangeM,
            )
            cameraToEstimatorDistanceM = Google3dCameraCommandGate.distanceM(
                lat,
                lon,
                frame.target.latitudeDeg,
                frame.target.longitudeDeg,
            )
            if (cameraCommandGate.shouldIssue(now, visualState, forceFollow)) {
                lastRequestedCamera = visualState
                googleMap.setCamera(visualState.toCamera())
                cameraCommands += 1
            }
        }
        waitingOverlay.visibility = View.GONE
        lastRenderCompletedMs = SystemClock.elapsedRealtime()
    }

    private fun updateTrajectory(googleMap: GoogleMap3D, snapshot: NavigationSnapshot, lat: Double, lon: Double) {
        val visualPoints = Google3dVisualTrajectory.decimate(snapshot.trajectory)
        val path = visualPoints.map {
            val point = MapCoordinateProjector.fromCurrentEnginePosition(it.eastM, it.northM, snapshot.state.eastM, snapshot.state.northM, lat, lon)
            LatLngAltitude(point.latitudeDeg, point.longitudeDeg, 1.0)
        }
        if (path.size >= 2) {
            trajectory = trajectory ?: googleMap.addPolyline(PolylineOptions().apply {
                id = "navghost_estimated_trajectory"
                altitudeMode = AltitudeMode.RELATIVE_TO_GROUND
                strokeColor = Color.rgb(0, 211, 184)
                outerColor = Color.argb(190, 3, 20, 34)
                strokeWidth = 4.5
                outerWidth = 7.5
                this.path = path
            })
            trajectory?.path = path
        }
    }

    private fun clearLivePosition() {
        marker?.remove()
        marker = null
        uncertainty?.remove()
        uncertainty = null
        cameraCommandGate.reset()
    }

    private fun updateUncertainty(googleMap: GoogleMap3D, snapshot: NavigationSnapshot, lat: Double, lon: Double) {
        val ring = True3dUncertaintyPolicy.ring(snapshot.state.horizontalUncertaintyM, UNCERTAINTY_SEGMENTS)
        if (ring.isEmpty()) { uncertainty?.remove(); uncertainty = null; return }
        val path = ring.map {
            val point = MapCoordinateProjector.fromCurrentEnginePosition(
                snapshot.state.eastM + it.eastM,
                snapshot.state.northM + it.northM,
                snapshot.state.eastM,
                snapshot.state.northM,
                lat,
                lon,
            )
            LatLngAltitude(point.latitudeDeg, point.longitudeDeg, 0.8)
        }
        uncertainty = uncertainty ?: googleMap.addPolyline(PolylineOptions().apply {
            id = "navghost_uncertainty"
            altitudeMode = AltitudeMode.RELATIVE_TO_GROUND
            strokeColor = MapStateStyle.color(snapshot.state.localizationMode)
            strokeWidth = 2.0
            this.path = path
        })
        uncertainty?.path = path
        uncertainty?.strokeColor = MapStateStyle.color(snapshot.state.localizationMode)
    }

    fun recenter() {
        following = true
        cameraSanityGate.reset()
        cameraPolicy.recenter()
        cameraCommandGate.reset()
        latestSnapshot.clear()
        render(lastSnapshot, forceCamera = true)
        if (isReady()) publish(readyPresentation())
    }
    fun setPerformanceProofMapMode(@Map3DMode mode: Int) {
        requestedMapMode = mode
        map?.setMapMode(mode)
    }
    fun performanceStats(nowMs: Long = SystemClock.elapsedRealtime()): Google3dPerformanceStats {
        val elapsedS = ((nowMs - performanceStartMs).coerceAtLeast(1L)) / 1_000.0
        return Google3dPerformanceStats(
            elapsedSeconds = elapsedS,
            offeredSnapshotHz = latestSnapshot.offeredCount / elapsedS,
            renderedSnapshotHz = renderedSnapshots / elapsedS,
            markerUpdateHz = markerUpdates / elapsedS,
            cameraCommandHz = cameraCommands / elapsedS,
            trajectoryUpdateHz = trajectoryUpdates / elapsedS,
            uncertaintyUpdateHz = uncertaintyUpdates / elapsedS,
            supersededSnapshots = latestSnapshot.supersededCount,
            offeredSnapshotAgeMs = latestOfferedSnapshotAgeMs,
            renderedSnapshotAgeMs = latestRenderedSnapshotAgeMs,
            lastRenderAgeMs = lastRenderCompletedMs.takeIf { it != Long.MIN_VALUE }
                ?.let { (nowMs - it).coerceAtLeast(0L).toDouble() },
            cameraToEstimatorDistanceM = cameraToEstimatorDistanceM,
        )
    }
    fun isFollowing(): Boolean = following
    fun isReady(): Boolean = lifecycle.state == RendererLifecycleState.READY
    fun state(): RendererLifecycleState = lifecycle.state
    fun status(): MapPresentation = presentation
    fun onStart() { if (lifecycle.state == RendererLifecycleState.INITIALIZING || isReady()) mapView.onStart() }
    fun onResume() { if (lifecycle.state == RendererLifecycleState.INITIALIZING || isReady()) mapView.onResume() }
    fun onPause() { if (lifecycle.state !in setOf(RendererLifecycleState.DISPOSING, RendererLifecycleState.DISPOSED)) mapView.onPause() }
    fun onStop() { if (lifecycle.state !in setOf(RendererLifecycleState.DISPOSING, RendererLifecycleState.DISPOSED)) mapView.onStop() }
    fun onLowMemory() { if (lifecycle.state !in setOf(RendererLifecycleState.DISPOSING, RendererLifecycleState.DISPOSED)) mapView.onLowMemory() }
    fun onDestroy() {
        if (!lifecycle.beginDisposal()) return
        mainHandler.removeCallbacksAndMessages(null)
        latestSnapshot.clear()
        renderScheduled = false
        if (Thread.getDefaultUncaughtExceptionHandler() === maps3dUncaughtHandler) {
            Thread.setDefaultUncaughtExceptionHandler(previousUncaughtHandler)
        }
        runCatching { marker?.remove(); trajectory?.remove(); uncertainty?.remove() }
        marker = null; trajectory = null; uncertainty = null; map = null
        mapView.onDestroy()
        lifecycle.finishDisposal()
    }

    private fun publish(value: MapPresentation) { if (value != presentation) { presentation = value; onStatus(value) } }
    private fun validateCamera(googleMap: GoogleMap3D) {
        if (lifecycle.state != RendererLifecycleState.READY) return
        val camera: Camera? = runCatching { googleMap.getCamera() }.getOrNull()
        val actual = camera?.let { current ->
            val center = current.getCenter()
            Google3dCameraVisualState(
                center.getLatitude(),
                center.getLongitude(),
                current.getHeading() ?: Double.NaN,
                current.getTilt() ?: Double.NaN,
                current.getRange() ?: Double.NaN,
            )
        }
        when (cameraSanityGate.observe(lastRequestedCamera, actual, following)) {
            CameraSanityAction.NONE -> Unit
            CameraSanityAction.RETRY -> lastRequestedCamera?.let {
                googleMap.setCamera(it.toCamera())
                cameraCommands += 1
            }
            CameraSanityAction.FAIL -> failSession("3D CAMERA COULD NOT REACH NAVGHOST POSITION")
        }
    }
    private fun Google3dCameraVisualState.toCamera() = Camera(
        LatLngAltitude(latitudeDeg, longitudeDeg, 0.0),
        bearingDeg,
        pitchDeg,
        0.0,
        rangeM,
    )
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
    private fun trajectorySignature(snapshot: NavigationSnapshot): Long {
        val points = snapshot.trajectory
        if (points.isEmpty()) return 0L
        val first = points.first()
        val last = points.last()
        return points.size.toLong() * 31L xor first.eastM.toBits() xor first.northM.toBits() xor
            last.eastM.toBits() xor last.northM.toBits() xor last.localizationMode.ordinal.toLong()
    }
    private fun loadingPresentation() = MapPresentation(PROVIDER_ID, MapAvailability.INITIALIZING, "GOOGLE 3D CONNECTING", "ENGINE ESTIMATE ONLY", ATTRIBUTION)
    private fun readyPresentation(detail: String = if (requestedMapMode == Map3DMode.HYBRID) "HYBRID 3D • ENGINE ESTIMATE ONLY" else "ROADMAP 3D • ENGINE ESTIMATE ONLY") =
        MapPresentation(PROVIDER_ID, MapAvailability.ONLINE_READY, "GOOGLE 3D READY", detail, ATTRIBUTION)
    companion object {
        const val PROVIDER_ID = "google_maps_3d"
        const val ATTRIBUTION = "Google"
        private const val VISUAL_INTERVAL_MS = 100L
        private const val CAMERA_INTERVAL_MS = 125L
        private const val HYBRID_FALLBACK_MS = 7_000L
        private const val UNCERTAINTY_SEGMENTS = 24
        internal fun sceneIsReady(sceneReadiness: Double): Boolean = sceneReadiness.isFinite() && sceneReadiness >= 1.0
        internal fun monotonicAgeMs(timestampNs: Long, nowNs: Long = SystemClock.elapsedRealtimeNanos()): Double? =
            timestampNs.takeIf { it > 0L && nowNs >= it }?.let { (nowNs - it) / 1e6 }
    }
}

data class Google3dPerformanceStats(
    val elapsedSeconds: Double,
    val offeredSnapshotHz: Double,
    val renderedSnapshotHz: Double,
    val markerUpdateHz: Double,
    val cameraCommandHz: Double,
    val trajectoryUpdateHz: Double,
    val uncertaintyUpdateHz: Double,
    val supersededSnapshots: Long,
    val offeredSnapshotAgeMs: Double?,
    val renderedSnapshotAgeMs: Double?,
    val lastRenderAgeMs: Double?,
    val cameraToEstimatorDistanceM: Double?,
)
