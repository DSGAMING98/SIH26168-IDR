package org.sih26168.idrlogger.ui

import android.annotation.SuppressLint

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.widget.FrameLayout
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.GoogleMap
import com.google.android.gms.maps.MapView
import com.google.android.gms.maps.MapsInitializer
import com.google.android.gms.maps.model.BitmapDescriptor
import com.google.android.gms.maps.model.BitmapDescriptorFactory
import com.google.android.gms.maps.model.Circle
import com.google.android.gms.maps.model.CircleOptions
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.MapStyleOptions
import com.google.android.gms.maps.model.Marker
import com.google.android.gms.maps.model.MarkerOptions
import com.google.android.gms.maps.model.Polyline
import com.google.android.gms.maps.model.PolylineOptions
import com.google.android.gms.maps3d.model.Map3DMode
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.R
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.map.EngineMarkerPolicy
import org.sih26168.idrlogger.map.Google3dCompatibilityPolicy
import org.sih26168.idrlogger.map.LocalEnuMapProvider
import org.sih26168.idrlogger.map.MapAvailability
import org.sih26168.idrlogger.map.MapCameraPolicy
import org.sih26168.idrlogger.map.MapCoordinateProjector
import org.sih26168.idrlogger.map.MapPresentation
import org.sih26168.idrlogger.map.MapLoadPolicy
import org.sih26168.idrlogger.map.ManualRendererCycle
import org.sih26168.idrlogger.map.MapStateStyle
import org.sih26168.idrlogger.map.NavGhostRenderer
import org.sih26168.idrlogger.map.RendererSelectionPolicy
import org.sih26168.idrlogger.map.RendererNetworkGate

/** Google Maps is only a canvas. Every marker and path point originates in an engine snapshot. */
class NavGhostMapSurface(
    context: Context,
    savedState: Bundle? = null,
    private val onDestinationSelected: (Double, Double) -> Unit = { _, _ -> },
    private val onStatus: (MapPresentation) -> Unit = {},
) : FrameLayout(context) {
    private enum class RendererPreference { AUTO, GOOGLE_3D, MAPLIBRE_3D, GOOGLE_LEGACY, LOCAL_ENU }
    private val localView = TrajectoryView(context)
    private val handler = Handler(Looper.getMainLooper())
    private val initialTrue3dState = savedState?.getBundle("true3d")
    private var true3dView: True3dMapSurface? = null
    private val google3dCompatible = Google3dCompatibilityPolicy.supports(Build.MANUFACTURER, Build.MODEL, Build.HARDWARE)
    private var google3dView: Google3dMapSurface? = if (google3dCompatible && BuildConfig.MAPS3D_CONFIGURED) {
        Google3dMapSurface(context, Map3DMode.HYBRID, ::onGoogle3dStatus)
    } else null
    private var mapView: MapView? = null
    private var map: GoogleMap? = null
    private var marker: Marker? = null
    private var uncertainty: Circle? = null
    private val trajectorySegments = mutableListOf<Polyline>()
    private var activeSegment: Polyline? = null
    private val activeSegmentPoints = mutableListOf<LatLng>()
    private var activeMode: LocalizationMode? = null
    private var lastTrajectorySize = 0
    private var firstTrajectoryKey: Pair<Double, Double>? = null
    private var lastSnapshot = NavigationSnapshot()
    private var mapLoaded = false
    private var useGoogle = false
    private var satellite = false
    private var manualLocal = false
    private var cameraPolicy = MapCameraPolicy(headingUp = true)
    private var presentation = LocalEnuMapProvider().presentation()
    private val loadPolicy = MapLoadPolicy(MAP_LOAD_TIMEOUT_MS)
    private val markerIcons = mutableMapOf<Int, BitmapDescriptor>()
    private var markerColor: Int? = null
    private var lastNetworkCheckMs = Long.MIN_VALUE
    private var networkAvailable = false
    private var failed = false
    private var started = false
    private var resumed = false
    private var destroyed = false
    private var mapConfigured = false
    private var cameraPlaced = false
    private var lastCameraInsets: Pair<Int, Int>? = null
    private var cameraLookAheadM = 0.0
    private val initialMapState = savedState?.getBundle("google") ?: savedState
    private val rendererPolicy = RendererSelectionPolicy(
        if (google3dView != null) NavGhostRenderer.GOOGLE_3D else NavGhostRenderer.MAPLIBRE_3D,
    )
    private var rendererPreference = RendererPreference.AUTO
    private var showTrail = true
    private var showUncertainty = true
    private var google3dUnavailable = false
    private var google3dOfflineFallback = false
    private var lastGoogle3dNetworkCheckMs = Long.MIN_VALUE
    private val google3dNetworkGate = RendererNetworkGate()
    private var renderer: NavGhostRenderer
        get() = rendererPolicy.active
        set(value) = rendererPolicy.select(value)
    private val servicesAvailable = runCatching {
        GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS
    }.getOrDefault(false)
    private val loadTimeout = Runnable {
        if (loadPolicy.timedOut(SystemClock.elapsedRealtime())) failMap("MAP TILES UNAVAILABLE • LOCAL NAVIGATION ACTIVE")
    }
    private val true3dTimeout = Runnable {
        if (renderer == NavGhostRenderer.MAPLIBRE_3D && true3dView?.isReady() != true) fallbackFromTrue3d("MAPLIBRE 3D TILES UNAVAILABLE")
    }
    private val google3dTimeout = Runnable {
        val view = google3dView
        if (renderer == NavGhostRenderer.GOOGLE_3D && view != null && !view.isReady()) {
            view.failSession("GOOGLE 3D STARTUP TIMED OUT")
        }
    }

    init {
        setBackgroundColor(Color.rgb(6, 13, 22))
        addView(localView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        localView.visibility = View.GONE
        google3dView?.let { view ->
            addView(view, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
            handler.postDelayed(google3dTimeout, GOOGLE_3D_LOAD_TIMEOUT_MS)
        } ?: run {
            ensureTrue3d().visibility = View.VISIBLE
            handler.postDelayed(true3dTimeout, TRUE_3D_LOAD_TIMEOUT_MS)
        }
    }

    fun show(snapshot: NavigationSnapshot, viewportMode: ViewportMode = ViewportMode.FOLLOW_CURRENT) {
        val presented = snapshot.copy(
            state = if (showUncertainty) snapshot.state else snapshot.state.copy(horizontalUncertaintyM = null),
            trajectory = if (showTrail) snapshot.trajectory else emptyList(),
        )
        lastSnapshot = presented
        refreshGoogle3dConnectivity()
        when (renderer) {
            NavGhostRenderer.GOOGLE_3D -> google3dView?.show(presented)
            NavGhostRenderer.MAPLIBRE_3D -> true3dView?.show(presented)
            NavGhostRenderer.LOCAL_ENU -> localView.show(presented, viewportMode, mapContext = presentation)
            NavGhostRenderer.GOOGLE_LEGACY -> {
                refreshMapAvailability()
                if (manualLocal || failed || destroyed) return
                val googleMap = map ?: return
                try { renderGoogleSnapshot(presented, googleMap) }
                catch (_: RuntimeException) { failMap("MAP RENDERING UNAVAILABLE • LOCAL NAVIGATION ACTIVE") }
            }
        }
    }

    private fun renderGoogleSnapshot(snapshot: NavigationSnapshot, googleMap: GoogleMap) {
        val state = snapshot.state
        val engineMarker = EngineMarkerPolicy.from(snapshot)
        val latitude = engineMarker.latitudeDeg
        val longitude = engineMarker.longitudeDeg
        if (latitude == null || longitude == null || !latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) {
            marker?.remove(); marker = null
            uncertainty?.remove(); uncertainty = null
            cameraPlaced = false
            return
        }
        val position = LatLng(latitude, longitude)
        val color = MapStateStyle.color(state.localizationMode)
        if (marker == null) {
            marker = googleMap.addMarker(
                MarkerOptions().position(position).flat(false).anchor(0.5f, 0.65f).icon(markerIcon(color))
                    .title("NavGhost estimated position").zIndex(20f)
            )
            markerColor = color
        }
        marker?.isVisible = true
        marker?.position = position
        // Billboard stays legible at 66-degree tilt; subtract map bearing to point at engine heading.
        if (engineMarker.headingDeg.isFinite()) marker?.rotation = engineMarker.headingDeg.toFloat() - googleMap.cameraPosition.bearing
        if (markerColor != color) { marker?.setIcon(markerIcon(color)); markerColor = color }
        val radius = state.horizontalUncertaintyM?.takeIf { it.isFinite() && it >= 0.0 }
        if (radius != null && uncertainty == null) {
            uncertainty = googleMap.addCircle(
                CircleOptions().center(position).radius(radius).strokeWidth(2.5f).zIndex(4f)
            )
        }
        uncertainty?.isVisible = radius != null
        if (radius != null) {
            uncertainty?.center = position
            uncertainty?.radius = radius
            uncertainty?.fillColor = (color and 0x00FFFFFF) or (18 shl 24)
            uncertainty?.strokeColor = (color and 0x00FFFFFF) or (100 shl 24)
        }
        updateTrajectory(snapshot)
        if (resumed && isShown && !(loadPolicy.loading && cameraPlaced) && cameraPolicy.shouldUpdate(SystemClock.elapsedRealtime())) {
            val frame = cameraPolicy.frame(engineMarker, state.speedMps, state.motionState, state.localizationMode,
                state.confidence == ConfidenceLevel.HIGH || state.confidence == ConfidenceLevel.MEDIUM) ?: return
            cameraLookAheadM = frame.lookAheadM
            updateCameraInsets()
            val camera = com.google.android.gms.maps.model.CameraPosition.Builder()
                .target(LatLng(frame.target.latitudeDeg, frame.target.longitudeDeg)).zoom(frame.zoom)
                .bearing(frame.bearingDeg).tilt(frame.tiltDeg).build()
            if (mapLoaded) googleMap.animateCamera(CameraUpdateFactory.newCameraPosition(camera), 240, null)
            else googleMap.moveCamera(CameraUpdateFactory.newCameraPosition(camera))
            cameraPlaced = true
        }
    }

    fun recenter() {
        if (renderer == NavGhostRenderer.GOOGLE_3D) {
            google3dView?.recenter()
            return
        }
        if (renderer == NavGhostRenderer.MAPLIBRE_3D) {
            true3dView?.recenter()
            return
        }
        cameraPolicy.recenter()
        localView.recenter()
        publishGoogleStatus()
        show(lastSnapshot)
    }

    fun toggleOrientation(): Boolean {
        if (renderer == NavGhostRenderer.GOOGLE_3D || renderer == NavGhostRenderer.MAPLIBRE_3D) return true
        cameraPolicy = MapCameraPolicy(headingUp = !cameraPolicy.headingUp)
        publishGoogleStatus()
        show(lastSnapshot)
        return cameraPolicy.headingUp
    }

    fun cycleMapLayer(): String {
        rendererPreference = when (ManualRendererCycle.next(renderer, BuildConfig.MAPS3D_CONFIGURED)) {
            NavGhostRenderer.GOOGLE_3D -> RendererPreference.GOOGLE_3D
            NavGhostRenderer.MAPLIBRE_3D -> RendererPreference.MAPLIBRE_3D
            NavGhostRenderer.GOOGLE_LEGACY -> RendererPreference.GOOGLE_LEGACY
            NavGhostRenderer.LOCAL_ENU -> RendererPreference.LOCAL_ENU
        }
        when (rendererPreference) {
            RendererPreference.AUTO -> restoreAutomatic()
            RendererPreference.GOOGLE_3D -> restoreGoogle3d()
            RendererPreference.MAPLIBRE_3D -> restoreTrue3d()
            RendererPreference.GOOGLE_LEGACY -> {
                renderer = NavGhostRenderer.GOOGLE_LEGACY
                true3dView?.visibility = View.GONE; google3dView?.visibility = View.GONE
                manualLocal = false; satellite = false; failed = false
                refreshMapAvailability(force = true)
                if (mapLoaded) restoreGoogle() else if (renderer == NavGhostRenderer.GOOGLE_LEGACY) showGooglePending()
            }
            RendererPreference.LOCAL_ENU -> {
                satellite = false; manualLocal = true
                showLocal("LOCAL ENU • MANUAL FALLBACK")
            }
        }
        return rendererSelectorLabel()
    }

    fun rendererSelectorLabel(): String = when (rendererPreference) {
        RendererPreference.AUTO -> "AUTO"
        RendererPreference.GOOGLE_3D -> "GOOGLE 3D"
        RendererPreference.MAPLIBRE_3D -> "MAPLIBRE 3D"
        RendererPreference.GOOGLE_LEGACY -> "GOOGLE LEGACY"
        RendererPreference.LOCAL_ENU -> "LOCAL ENU"
    }

    fun setPresentationOptions(trail: Boolean, uncertaintyVisible: Boolean) {
        showTrail = trail; showUncertainty = uncertaintyVisible
        if (!trail) rebuildTrajectory()
        show(lastSnapshot)
    }

    fun selectRendererPreference(label: String) {
        rendererPreference = runCatching { RendererPreference.valueOf(label.trim().uppercase().replace(' ', '_')) }
            .getOrDefault(RendererPreference.AUTO)
        when (rendererPreference) {
            RendererPreference.AUTO -> restoreAutomatic()
            RendererPreference.GOOGLE_3D -> restoreGoogle3d()
            RendererPreference.MAPLIBRE_3D -> restoreTrue3d()
            RendererPreference.GOOGLE_LEGACY -> {
                renderer = NavGhostRenderer.GOOGLE_LEGACY
                manualLocal = false; satellite = false; failed = false
                refreshMapAvailability(force = true)
                if (mapLoaded) restoreGoogle() else if (renderer == NavGhostRenderer.GOOGLE_LEGACY) showGooglePending()
            }
            RendererPreference.LOCAL_ENU -> { manualLocal = true; showLocal("LOCAL ENU • MANUAL FALLBACK") }
        }
    }

    fun isGoogleMapActive(): Boolean = useGoogle
    fun supportsGoogleMap(): Boolean = BuildConfig.MAPS_CONFIGURED && servicesAvailable
    fun status(): MapPresentation = presentation
    fun google3dPerformanceStats(): Google3dPerformanceStats = google3dView?.performanceStats()
        ?: Google3dPerformanceStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0L, null, null, null, null)
    fun mapModeLabel(): String = when {
        renderer == NavGhostRenderer.GOOGLE_3D -> "GOOGLE_3D"
        renderer == NavGhostRenderer.MAPLIBRE_3D -> "MAPLIBRE_3D"
        !useGoogle -> "LOCAL"
        satellite -> "SATELLITE"
        cameraPolicy.headingUp -> "CINEMATIC"
        else -> "NORTH_UP"
    }
    fun isFollowing(): Boolean = when (renderer) {
        NavGhostRenderer.GOOGLE_3D -> google3dView?.isFollowing() == true
        NavGhostRenderer.MAPLIBRE_3D -> true3dView?.isFollowing() == true
        else -> cameraPolicy.following
    }
    fun isCinematic(): Boolean = renderer == NavGhostRenderer.GOOGLE_3D || renderer == NavGhostRenderer.MAPLIBRE_3D || cameraPolicy.headingUp
    fun layerLabel(): String = when (renderer) {
        NavGhostRenderer.GOOGLE_3D -> "GOOGLE 3D"
        NavGhostRenderer.MAPLIBRE_3D -> "MAPLIBRE 3D"
        NavGhostRenderer.GOOGLE_LEGACY -> "GOOGLE LEGACY"
        NavGhostRenderer.LOCAL_ENU -> "LOCAL ENU"
    }
    fun supportsMapLayers(): Boolean = true

    // Padding shifts the camera's optical centre down without shifting the actual marker coordinate.
    // Reserve the bottom HUD plus Google attribution; the forward target adds the moving corridor.
    private fun updateCameraInsets() {
        val bottom = (96 * resources.displayMetrics.density).toInt().coerceAtMost(height / 4)
        // Moving perspective already pushes the marker down. Reserve more top space at rest,
        // easing that bias out with look-ahead so the marker remains near the lower third.
        val bias = 0.40 - 0.24 * (cameraLookAheadM / 55.0).coerceIn(0.0, 1.0)
        val top = if (cameraPolicy.headingUp) ((height - bottom) * bias).toInt() else 0
        if (map != null && lastCameraInsets != (top to bottom)) {
            map?.setPadding(0, top, 0, bottom)
            lastCameraInsets = top to bottom
        }
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        updateCameraInsets()
    }

    fun onStart() { started = true; google3dView?.onStart(); true3dView?.onStart(); mapView?.onStart() }
    fun onResume() { resumed = true; google3dView?.onResume(); true3dView?.onResume(); mapView?.onResume(); if (renderer == NavGhostRenderer.GOOGLE_LEGACY) refreshMapAvailability(force = true) }
    fun onPause() {
        resumed = false
        map?.stopAnimation()
        google3dView?.onPause()
        true3dView?.onPause()
        handler.removeCallbacks(loadTimeout)
        loadPolicy.fail() // Rendering may stop in background; resume starts a fresh bounded watch.
        mapView?.onPause()
    }
    fun onStop() { started = false; google3dView?.onStop(); true3dView?.onStop(); mapView?.onStop() }
    fun onDestroy() { destroyed = true; handler.removeCallbacksAndMessages(null); google3dView?.onDestroy(); true3dView?.onDestroy(); mapView?.onDestroy(); markerIcons.clear() }
    fun onLowMemory() { google3dView?.onLowMemory(); true3dView?.onLowMemory(); mapView?.onLowMemory() }
    fun onSaveInstanceState(outState: Bundle) {
        true3dView?.let { view -> val state = Bundle(); view.onSaveInstanceState(state); outState.putBundle("true3d", state) }
        val google = Bundle(); mapView?.onSaveInstanceState(google); outState.putBundle("google", google)
    }

    private fun initializeGoogle(savedState: Bundle?) {
        try {
            MapsInitializer.initialize(context)
            val view = MapView(context)
            mapView = view
            addView(view, 0, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
            view.onCreate(savedState)
            if (started) view.onStart()
            if (resumed) view.onResume()
            watchTileLoad(hidePending = true)
            view.getMapAsync(::onMapReady)
        } catch (_: Throwable) {
            failMap("MAP INITIALIZATION UNAVAILABLE • LOCAL NAVIGATION ACTIVE")
        }
    }

    private fun onMapReady(googleMap: GoogleMap) {
        if (destroyed) return
        map = googleMap
        if (failed) return
        try { configureMap(googleMap) }
        catch (_: RuntimeException) { failMap("MAP INITIALIZATION UNAVAILABLE • LOCAL NAVIGATION ACTIVE") }
    }

    @SuppressLint("MissingPermission") // Setting false disables the permission-gated blue dot.
    private fun configureMap(googleMap: GoogleMap) {
        googleMap.isMyLocationEnabled = false
        googleMap.uiSettings.isMyLocationButtonEnabled = false
        googleMap.uiSettings.isMapToolbarEnabled = false
        googleMap.uiSettings.isCompassEnabled = false
        runCatching { googleMap.isBuildingsEnabled = true } // Optional renderer capability.
        runCatching { googleMap.setMapStyle(MapStyleOptions.loadRawResourceStyle(context, R.raw.navghost_map_style)) }
        googleMap.setOnCameraMoveStartedListener { reason ->
            if (reason == GoogleMap.OnCameraMoveStartedListener.REASON_GESTURE) {
                googleMap.stopAnimation()
                cameraPolicy.onUserGesture()
                publishGoogleStatus()
            }
        }
        googleMap.setOnCameraMoveListener {
            val heading = lastSnapshot.state.headingDeg
            if (heading.isFinite()) marker?.rotation = heading.toFloat() - googleMap.cameraPosition.bearing
        }
        googleMap.setOnMapLongClickListener { point ->
            cameraPolicy.onUserGesture()
            publishGoogleStatus()
            onDestinationSelected(point.latitude, point.longitude)
        }
        // Do not restart a tile watchdog on every chase frame: continuous animations can defer
        // onMapLoaded indefinitely. Watch initial/layer loads; connectivity failures remain independent.
        updateCameraInsets()
        mapConfigured = true
        installTileCallback()
        show(lastSnapshot)
    }

    private fun watchTileLoad(hidePending: Boolean) {
        if (destroyed || !resumed || manualLocal || failed || loadPolicy.loading) return
        loadPolicy.begin(SystemClock.elapsedRealtime())
        if (hidePending) {
            useGoogle = false
            mapView?.visibility = View.VISIBLE // Keep loading behind the opaque, usable ENU view.
            localView.visibility = View.VISIBLE
            publish(MapPresentation("google_maps", MapAvailability.INITIALIZING, "MAP CONNECTING", "LOCAL NAVIGATION ACTIVE", "Google"))
        }
        installTileCallback()
        handler.removeCallbacks(loadTimeout)
        handler.postDelayed(loadTimeout, MAP_LOAD_TIMEOUT_MS)
    }

    private fun installTileCallback() {
        map?.setOnMapLoadedCallback {
            if (loadPolicy.timedOut(SystemClock.elapsedRealtime())) {
                failMap("MAP TILES UNAVAILABLE • LOCAL NAVIGATION ACTIVE")
                return@setOnMapLoadedCallback
            }
            if (!destroyed && loadPolicy.onTilesLoaded(SystemClock.elapsedRealtime())) {
                handler.removeCallbacks(loadTimeout)
                mapLoaded = true
                if (!manualLocal && hasValidatedNetwork()) restoreGoogle()
            }
        }
    }

    private fun refreshMapAvailability(force: Boolean = false) {
        if (destroyed || renderer != NavGhostRenderer.GOOGLE_LEGACY) return
        val now = SystemClock.elapsedRealtime()
        if (!force && lastNetworkCheckMs != Long.MIN_VALUE && now - lastNetworkCheckMs < NETWORK_CHECK_INTERVAL_MS) return
        lastNetworkCheckMs = now
        if (!BuildConfig.MAPS_CONFIGURED) { showLocal("LOCAL MAP • OPTIONAL GOOGLE KEY NOT CONFIGURED"); return }
        if (!servicesAvailable) { showLocal("MAP SERVICE UNAVAILABLE • LOCAL NAVIGATION ACTIVE"); return }
        val wasAvailable = networkAvailable
        networkAvailable = hasValidatedNetwork()
        if (!networkAvailable) {
            failMap("MAP OFFLINE • LOCAL NAVIGATION ACTIVE")
            return
        }
        if (manualLocal) return
        if (!wasAvailable) failed = false // One retry on connectivity recovery, not every estimator sample.
        if (failed) return
        if (mapView == null) initializeGoogle(initialMapState)
        else if (!mapLoaded && !loadPolicy.loading) {
            watchTileLoad(hidePending = true)
            if (!mapConfigured) mapView?.getMapAsync(::onMapReady)
        }
    }

    private fun failMap(detail: String) {
        failed = true
        mapLoaded = false
        loadPolicy.fail()
        handler.removeCallbacks(loadTimeout)
        showLocal(detail)
    }

    private fun showLocal(detail: String) {
        renderer = NavGhostRenderer.LOCAL_ENU
        useGoogle = false
        google3dView?.visibility = View.GONE
        true3dView?.visibility = View.GONE
        mapView?.visibility = View.GONE
        localView.visibility = View.VISIBLE
        publish(LocalEnuMapProvider().presentation().copy(detailLabel = detail))
        localView.show(lastSnapshot, mapContext = presentation)
    }

    private fun showGooglePending() {
        renderer = NavGhostRenderer.GOOGLE_LEGACY
        useGoogle = false
        google3dView?.visibility = View.GONE
        true3dView?.visibility = View.GONE
        mapView?.visibility = View.VISIBLE
        localView.visibility = View.VISIBLE
        publish(MapPresentation("google_maps", MapAvailability.INITIALIZING, "GOOGLE MAP CONNECTING", "LOCAL ENU REMAINS ACTIVE UNTIL TILES LOAD", "Google"))
        localView.show(lastSnapshot, mapContext = presentation)
    }

    private fun restoreGoogle() {
        val googleMap = map ?: return
        if (destroyed || failed || manualLocal || !mapLoaded) return
        useGoogle = true
        renderer = NavGhostRenderer.GOOGLE_LEGACY
        google3dView?.visibility = View.GONE
        true3dView?.visibility = View.GONE
        localView.visibility = View.GONE
        mapView?.visibility = View.VISIBLE
        val type = if (satellite) GoogleMap.MAP_TYPE_SATELLITE else GoogleMap.MAP_TYPE_NORMAL
        if (googleMap.mapType != type) googleMap.mapType = type
        publishGoogleStatus()
        show(lastSnapshot)
    }

    private fun publishGoogleStatus() {
        if (!useGoogle) return
        val mode = "${if (satellite) "SATELLITE" else "MAP"} • ${if (cameraPolicy.headingUp) "CINEMATIC" else "NORTH-UP"}"
        val detail = if (cameraPolicy.following) "$mode • NAVGHOST ESTIMATE" else "FOLLOW PAUSED • TAP RECENTER"
        publish(MapPresentation("google_maps", MapAvailability.ONLINE_READY, "MAP READY", detail, "Google"))
    }

    private fun onTrue3dStatus(value: MapPresentation) {
        if (value.availability == MapAvailability.ONLINE_READY) {
            handler.removeCallbacks(true3dTimeout)
            if (renderer == NavGhostRenderer.MAPLIBRE_3D) restoreTrue3d()
        } else if (value.availability == MapAvailability.NETWORK_UNAVAILABLE && renderer == NavGhostRenderer.MAPLIBRE_3D) {
            fallbackFromTrue3d(value.detailLabel)
        } else if (renderer == NavGhostRenderer.MAPLIBRE_3D) publish(value)
    }

    private fun restoreTrue3d() {
        val view = ensureTrue3d()
        renderer = NavGhostRenderer.MAPLIBRE_3D
        useGoogle = false
        google3dView?.visibility = View.GONE
        mapView?.visibility = View.GONE
        localView.visibility = View.GONE
        view.visibility = View.VISIBLE
        publish(view.status())
        view.show(lastSnapshot)
    }

    private fun fallbackFromTrue3d(detail: String) {
        rendererPolicy.onMapLibreFailure(supportsGoogleMap())
        true3dView?.visibility = View.GONE
        publish(MapPresentation("maplibre_openfreemap_3d", MapAvailability.NETWORK_UNAVAILABLE, "TRUE 3D UNAVAILABLE", "$detail • FALLBACK ACTIVE", True3dMapSurface.ATTRIBUTION))
        refreshMapAvailability(force = true)
        if (!supportsGoogleMap()) showLocal("$detail • LOCAL NAVIGATION ACTIVE")
    }

    private fun onGoogle3dStatus(value: MapPresentation) {
        if (value.availability == MapAvailability.ONLINE_READY) {
            handler.removeCallbacks(google3dTimeout)
            if (renderer == NavGhostRenderer.GOOGLE_3D) restoreGoogle3d()
        } else if (value.availability == MapAvailability.NETWORK_UNAVAILABLE && renderer == NavGhostRenderer.GOOGLE_3D) {
            fallbackFromGoogle3d(value.detailLabel)
        } else if (renderer == NavGhostRenderer.GOOGLE_3D) publish(value)
    }

    private fun restoreGoogle3d() {
        if (!BuildConfig.MAPS3D_CONFIGURED) { restoreTrue3d(); return }
        if (!hasValidatedNetwork()) {
            google3dOfflineFallback = true
            google3dNetworkGate.reset()
            showLocal("3D MAP OFFLINE • NAVGHOST POSITION REMAINS ACTIVE")
            return
        }
        google3dOfflineFallback = false
        google3dNetworkGate.reset()
        val view = ensureGoogle3d(explicit = true)
        renderer = NavGhostRenderer.GOOGLE_3D
        useGoogle = false; manualLocal = false
        true3dView?.visibility = View.GONE; mapView?.visibility = View.GONE; localView.visibility = View.GONE
        view.visibility = View.VISIBLE
        publish(view.status())
        view.show(lastSnapshot)
        handler.removeCallbacks(google3dTimeout)
        handler.postDelayed(google3dTimeout, GOOGLE_3D_LOAD_TIMEOUT_MS)
    }

    private fun restoreAutomatic() {
        manualLocal = false
        when {
            google3dView?.isReady() == true -> restoreGoogle3d()
            true3dView?.isReady() == true -> restoreTrue3d()
            supportsGoogleMap() && mapLoaded -> restoreGoogle()
            else -> showLocal("AUTO • RENDERERS CONNECTING • LOCAL ENU ACTIVE")
        }
    }

    private fun fallbackFromGoogle3d(detail: String) {
        if (google3dUnavailable && renderer != NavGhostRenderer.GOOGLE_3D) return
        google3dUnavailable = true
        rendererPolicy.onGoogle3dFailure()
        google3dView?.visibility = View.GONE
        val fallback = ensureTrue3d()
        fallback.visibility = View.VISIBLE
        publish(MapPresentation(Google3dMapSurface.PROVIDER_ID, MapAvailability.NETWORK_UNAVAILABLE, "GOOGLE 3D UNAVAILABLE", "$detail • MAPLIBRE 3D FALLBACK", Google3dMapSurface.ATTRIBUTION))
        handler.postDelayed(true3dTimeout, TRUE_3D_LOAD_TIMEOUT_MS)
        if (fallback.isReady()) restoreTrue3d()
    }

    private fun refreshGoogle3dConnectivity() {
        if (destroyed) return
        val watchesGoogle3d = renderer == NavGhostRenderer.GOOGLE_3D || google3dOfflineFallback
        if (!watchesGoogle3d) return
        val now = SystemClock.elapsedRealtime()
        if (lastGoogle3dNetworkCheckMs != Long.MIN_VALUE && now - lastGoogle3dNetworkCheckMs < NETWORK_CHECK_INTERVAL_MS) return
        lastGoogle3dNetworkCheckMs = now
        val validated = hasValidatedNetwork()
        if (validated) {
            google3dNetworkGate.reset()
            if (google3dOfflineFallback) restoreGoogle3d()
        } else if (renderer == NavGhostRenderer.GOOGLE_3D && google3dNetworkGate.shouldFallback(false)) {
            google3dOfflineFallback = true
            showLocal("3D MAP OFFLINE • NAVGHOST POSITION REMAINS ACTIVE")
        }
    }

    private fun ensureTrue3d(): True3dMapSurface {
        true3dView?.let { return it }
        check(Looper.myLooper() == Looper.getMainLooper()) { "Renderer creation must run on the main thread" }
        return True3dMapSurface(context, initialTrue3dState, onDestinationSelected) { value ->
            handler.post { if (!destroyed) onTrue3dStatus(value) }
        }.also { view ->
            true3dView = view
            view.visibility = View.GONE
            addView(view, 1, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
            if (started) view.onStart()
            if (resumed) view.onResume()
        }
    }

    private fun ensureGoogle3d(explicit: Boolean): Google3dMapSurface {
        google3dView?.takeIf { !google3dUnavailable }?.let { return it }
        google3dView?.let { old ->
            old.onPause(); old.onStop(); old.onDestroy(); removeView(old)
        }
        google3dUnavailable = false
        val mode = if (google3dCompatible) Map3DMode.HYBRID else Map3DMode.ROADMAP
        return Google3dMapSurface(context, mode) { value ->
            handler.post { if (!destroyed) onGoogle3dStatus(value) }
        }.also { view ->
            google3dView = view
            view.visibility = if (explicit) View.VISIBLE else View.GONE
            addView(view, 2, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
            if (started) view.onStart()
            if (resumed) view.onResume()
        }
    }

    private fun publish(value: MapPresentation) {
        if (value != presentation) { presentation = value; onStatus(value) }
    }

    private fun hasValidatedNetwork(): Boolean = runCatching {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return@runCatching false
        val network = manager.activeNetwork ?: return@runCatching false
        val capabilities = manager.getNetworkCapabilities(network) ?: return@runCatching false
        capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }.getOrDefault(false)

    private fun updateTrajectory(snapshot: NavigationSnapshot) {
        val state = snapshot.state
        val latitude = state.latitudeDeg ?: return
        val longitude = state.longitudeDeg ?: return
        val points = snapshot.trajectory
        val first = points.firstOrNull()?.let { it.eastM to it.northM }
        if (points.size < lastTrajectorySize || (lastTrajectorySize == points.size && first != firstTrajectoryKey)) rebuildTrajectory()
        if (points.isEmpty()) return
        for (index in lastTrajectorySize until points.size) appendTrajectoryPoint(points[index], state.eastM, state.northM, latitude, longitude)
        flushActiveSegment()
        lastTrajectorySize = points.size
        firstTrajectoryKey = first
    }

    private fun rebuildTrajectory() {
        trajectorySegments.forEach(Polyline::remove)
        trajectorySegments.clear(); activeSegment = null; activeMode = null; activeSegmentPoints.clear(); lastTrajectorySize = 0
    }

    private fun appendTrajectoryPoint(point: TrajectoryPoint, currentEast: Double, currentNorth: Double, currentLat: Double, currentLon: Double) {
        val projected = MapCoordinateProjector.fromCurrentEnginePosition(point.eastM, point.northM, currentEast, currentNorth, currentLat, currentLon)
        val latLng = LatLng(projected.latitudeDeg, projected.longitudeDeg)
        if (activeMode != point.localizationMode || activeSegment == null) {
            flushActiveSegment()
            activeMode = point.localizationMode
            val continuity = activeSegmentPoints.lastOrNull()
            activeSegmentPoints.clear()
            continuity?.let(activeSegmentPoints::add)
            activeSegment = map?.addPolyline(
                PolylineOptions().color(MapStateStyle.color(point.localizationMode)).width(MapStateStyle.pathWidth(point.localizationMode)).zIndex(8f)
            )?.also(trajectorySegments::add)
        }
        activeSegmentPoints += latLng
    }

    private fun flushActiveSegment() {
        if (activeSegmentPoints.isNotEmpty()) activeSegment?.points = activeSegmentPoints.toList()
    }

    private fun markerIcon(color: Int): BitmapDescriptor = markerIcons.getOrPut(color) {
        val size = (28 * resources.displayMetrics.density).toInt().coerceAtLeast(28)
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.scale(size / 48f, size / 48f)
        val arrow = Path().apply { moveTo(24f, 4f); lineTo(41f, 42f); lineTo(24f, 34f); lineTo(7f, 42f); close() }
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeJoin = Paint.Join.ROUND }
        paint.style = Paint.Style.STROKE; paint.strokeWidth = 5f; paint.color = Color.rgb(6, 16, 26)
        canvas.drawPath(arrow, paint)
        paint.style = Paint.Style.FILL; paint.color = color; canvas.drawPath(arrow, paint)
        paint.style = Paint.Style.STROKE; paint.strokeWidth = 1.4f; paint.color = Color.WHITE; canvas.drawPath(arrow, paint)
        BitmapDescriptorFactory.fromBitmap(bitmap)
    }
    companion object {
        private const val MAP_LOAD_TIMEOUT_MS = 12_000L
        private const val TRUE_3D_LOAD_TIMEOUT_MS = 15_000L
        private const val GOOGLE_3D_LOAD_TIMEOUT_MS = 14_000L
        private const val NETWORK_CHECK_INTERVAL_MS = 2_000L
    }

}
