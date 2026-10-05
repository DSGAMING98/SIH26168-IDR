package org.sih26168.idrlogger.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.os.Bundle
import android.os.SystemClock
import android.widget.FrameLayout
import org.maplibre.android.MapLibre
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.Style
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.FillExtrusionLayer
import org.maplibre.android.style.layers.FillLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.Property
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.layers.SymbolLayer
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.geojson.Feature
import org.maplibre.geojson.FeatureCollection
import org.maplibre.geojson.LineString
import org.maplibre.geojson.Point
import org.maplibre.geojson.Polygon
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.map.EngineMarkerPolicy
import org.sih26168.idrlogger.map.MapAvailability
import org.sih26168.idrlogger.map.MapCoordinateProjector
import org.sih26168.idrlogger.map.MapPresentation
import org.sih26168.idrlogger.map.MapStateStyle
import org.sih26168.idrlogger.map.True3dCameraPolicy
import org.sih26168.idrlogger.map.True3dUncertaintyPolicy
import kotlin.math.PI
import kotlin.math.cos

/**
 * True vector 3D presentation surface. OpenFreeMap supplies visual context only; the marker,
 * uncertainty and travelled history are derived exclusively from [NavigationSnapshot].
 */
class True3dMapSurface(
    context: Context,
    savedState: Bundle? = null,
    private val onDestinationSelected: (Double, Double) -> Unit = { _, _ -> },
    private val onStatus: (MapPresentation) -> Unit = {},
) : FrameLayout(context) {
    private val mapView: MapView
    private var map: MapLibreMap? = null
    private var style: Style? = null
    private val cameraPolicy = True3dCameraPolicy()
    private var lastSnapshot = NavigationSnapshot()
    private var ready = false
    private var failed = false
    private var resumed = false
    private var presentation = MapPresentation(PROVIDER_ID, MapAvailability.INITIALIZING, "TRUE 3D CONNECTING", "VECTOR BUILDINGS LOADING", ATTRIBUTION)

    init {
        setBackgroundColor(Color.rgb(6, 13, 22))
        MapLibre.getInstance(context.applicationContext)
        mapView = MapView(context)
        addView(mapView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        mapView.onCreate(savedState)
        mapView.getMapAsync(::configureMap)
    }

    fun show(snapshot: NavigationSnapshot) {
        lastSnapshot = snapshot
        val activeStyle = style ?: return
        val marker = EngineMarkerPolicy.from(snapshot)
        val latitude = marker.latitudeDeg
        val longitude = marker.longitudeDeg
        if (latitude == null || longitude == null || !validCoordinate(latitude, longitude)) {
            clearLivePosition(activeStyle)
            return
        }
        val point = Point.fromLngLat(longitude, latitude)
        val markerFeature = Feature.fromGeometry(point).apply {
            addStringProperty("icon", markerImage(snapshot.state.localizationMode))
            addNumberProperty("heading", marker.headingDeg)
        }
        activeStyle.getSourceAs<GeoJsonSource>(MARKER_SOURCE)?.setGeoJson(markerFeature)
        updateUncertainty(activeStyle, snapshot, point)
        updateHistory(activeStyle, snapshot, latitude, longitude)

        if (resumed && cameraPolicy.shouldUpdate(SystemClock.elapsedRealtime())) {
            val frame = cameraPolicy.frame(
                marker, snapshot.state.speedMps, snapshot.state.motionState, snapshot.state.localizationMode,
                snapshot.state.confidence == ConfidenceLevel.HIGH || snapshot.state.confidence == ConfidenceLevel.MEDIUM,
            ) ?: return
            val position = CameraPosition.Builder()
                .target(LatLng(frame.target.latitudeDeg, frame.target.longitudeDeg))
                .bearing(frame.bearingDeg).tilt(frame.pitchDeg).zoom(frame.zoom).build()
            map?.easeCamera(CameraUpdateFactory.newCameraPosition(position), CAMERA_DURATION_MS)
        }
    }

    fun recenter() { cameraPolicy.recenter(); show(lastSnapshot) }
    fun isFollowing(): Boolean = cameraPolicy.following
    fun isReady(): Boolean = ready && !failed
    fun status(): MapPresentation = presentation

    fun onStart() = mapView.onStart()
    fun onResume() { resumed = true; mapView.onResume(); show(lastSnapshot) }
    fun onPause() { resumed = false; mapView.onPause() }
    fun onStop() = mapView.onStop()
    fun onDestroy() = mapView.onDestroy()
    fun onLowMemory() = mapView.onLowMemory()
    fun onSaveInstanceState(outState: Bundle) = mapView.onSaveInstanceState(outState)

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        updateCameraInsets(w, h)
    }

    private fun configureMap(value: MapLibreMap) {
        map = value
        updateCameraInsets(width, height)
        value.uiSettings.apply {
            isAttributionEnabled = true
            isLogoEnabled = true
            isCompassEnabled = false
            isRotateGesturesEnabled = true
            isTiltGesturesEnabled = true
            isZoomGesturesEnabled = true
            isScrollGesturesEnabled = true
        }
        value.addOnCameraMoveStartedListener { reason ->
            if (reason == MapLibreMap.OnCameraMoveStartedListener.REASON_API_GESTURE) {
                cameraPolicy.onUserGesture()
                publish(presentation.copy(detailLabel = "FOLLOW PAUSED • TAP RECENTER"))
            }
        }
        value.addOnMapLongClickListener { point ->
            cameraPolicy.onUserGesture()
            publish(presentation.copy(detailLabel = "DESTINATION SELECTED • OPENING DIRECTIONS"))
            onDestinationSelected(point.latitude, point.longitude)
            true
        }
        value.setStyle(Style.Builder().fromUri(STYLE_URI)) { loadedStyle ->
            runCatching { installStyle(loadedStyle) }
                .onSuccess {
                    style = loadedStyle
                    ready = true
                    publish(MapPresentation(PROVIDER_ID, MapAvailability.ONLINE_READY, "TRUE 3D READY", "OPEN VECTOR BUILDINGS • NAVGHOST ESTIMATE", ATTRIBUTION))
                    show(lastSnapshot)
                }
                .onFailure { fail("TRUE 3D STYLE UNAVAILABLE") }
        }
    }

    private fun installStyle(value: Style) {
        val extrusion = FillExtrusionLayer(BUILDING_LAYER, OPEN_MAP_SOURCE)
            .withSourceLayer(BUILDING_SOURCE_LAYER)
            .withFilter(Expression.all(Expression.has("render_height"), Expression.has("render_min_height")))
            .withProperties(
                PropertyFactory.fillExtrusionColor("#C7D2DF"),
                PropertyFactory.fillExtrusionHeight(Expression.get("render_height")),
                PropertyFactory.fillExtrusionBase(Expression.get("render_min_height")),
                PropertyFactory.fillExtrusionOpacity(0.88f),
                PropertyFactory.fillExtrusionVerticalGradient(true),
            )
        extrusion.minZoom = 14.5f
        val firstLabel = value.layers.firstOrNull { it is SymbolLayer }?.id
        if (firstLabel == null) value.addLayer(extrusion) else value.addLayerBelow(extrusion, firstLabel)

        value.addSource(GeoJsonSource(HISTORY_GNSS_SOURCE, FeatureCollection.fromFeatures(emptyArray())))
        value.addSource(GeoJsonSource(HISTORY_IDR_SOURCE, FeatureCollection.fromFeatures(emptyArray())))
        value.addSource(GeoJsonSource(HISTORY_RECOVERY_SOURCE, FeatureCollection.fromFeatures(emptyArray())))
        addHistoryLayer(value, HISTORY_GNSS_LAYER, HISTORY_GNSS_SOURCE, "#4AD8B5")
        addHistoryLayer(value, HISTORY_IDR_LAYER, HISTORY_IDR_SOURCE, "#FFAE48")
        addHistoryLayer(value, HISTORY_RECOVERY_LAYER, HISTORY_RECOVERY_SOURCE, "#967EFF")

        value.addSource(GeoJsonSource(UNCERTAINTY_SOURCE, FeatureCollection.fromFeatures(emptyArray())))
        value.addLayer(FillLayer(UNCERTAINTY_LAYER, UNCERTAINTY_SOURCE).withProperties(
            PropertyFactory.fillColor("#4AD8B5"), PropertyFactory.fillOpacity(0.14f),
            PropertyFactory.fillOutlineColor("#7CEAD0"),
        ))
        value.addSource(GeoJsonSource(MARKER_SOURCE, Point.fromLngLat(0.0, 0.0)))
        value.addImage(MARKER_GNSS_IMAGE, markerBitmap(MapStateStyle.color(LocalizationMode.GNSS_ACTIVE)))
        value.addImage(MARKER_IDR_IMAGE, markerBitmap(MapStateStyle.color(LocalizationMode.IDR_ACTIVE)))
        value.addImage(MARKER_RECOVERY_IMAGE, markerBitmap(MapStateStyle.color(LocalizationMode.GNSS_RECOVERING)))
        value.addImage(MARKER_ERROR_IMAGE, markerBitmap(MapStateStyle.color(LocalizationMode.ERROR)))
        value.addImage(MARKER_NEUTRAL_IMAGE, markerBitmap(MapStateStyle.color(LocalizationMode.WAITING_FOR_GNSS)))
        value.addLayer(SymbolLayer(MARKER_LAYER, MARKER_SOURCE).withProperties(
            PropertyFactory.iconImage(Expression.get("icon")),
            PropertyFactory.iconRotate(Expression.get("heading")),
            PropertyFactory.iconSize(0.52f),
            PropertyFactory.iconAllowOverlap(true),
            PropertyFactory.iconIgnorePlacement(true),
            PropertyFactory.iconRotationAlignment(Property.ICON_ROTATION_ALIGNMENT_MAP),
        ))
    }

    private fun addHistoryLayer(style: Style, layerId: String, sourceId: String, color: String) {
        style.addLayer(LineLayer(layerId, sourceId).withProperties(
            PropertyFactory.lineColor(color), PropertyFactory.lineWidth(6f),
            PropertyFactory.lineOpacity(0.9f), PropertyFactory.lineCap(Property.LINE_CAP_ROUND),
            PropertyFactory.lineJoin(Property.LINE_JOIN_ROUND),
        ))
    }

    private fun updateHistory(activeStyle: Style, snapshot: NavigationSnapshot, lat: Double, lon: Double) {
        val grouped = mutableMapOf<String, MutableList<Point>>()
        snapshot.trajectory.forEach { point ->
            val source = historySource(point.localizationMode)
            val geo = MapCoordinateProjector.fromCurrentEnginePosition(point.eastM, point.northM, snapshot.state.eastM, snapshot.state.northM, lat, lon)
            grouped.getOrPut(source) { mutableListOf() }.add(Point.fromLngLat(geo.longitudeDeg, geo.latitudeDeg))
        }
        listOf(HISTORY_GNSS_SOURCE, HISTORY_IDR_SOURCE, HISTORY_RECOVERY_SOURCE).forEach { sourceId ->
            val points = grouped[sourceId].orEmpty()
            val features = if (points.size >= 2) arrayOf(Feature.fromGeometry(LineString.fromLngLats(points))) else emptyArray()
            activeStyle.getSourceAs<GeoJsonSource>(sourceId)?.setGeoJson(FeatureCollection.fromFeatures(features))
        }
    }

    private fun clearLivePosition(activeStyle: Style) {
        activeStyle.getSourceAs<GeoJsonSource>(MARKER_SOURCE)
            ?.setGeoJson(FeatureCollection.fromFeatures(emptyArray()))
        activeStyle.getSourceAs<GeoJsonSource>(UNCERTAINTY_SOURCE)
            ?.setGeoJson(FeatureCollection.fromFeatures(emptyArray()))
    }

    private fun updateUncertainty(activeStyle: Style, snapshot: NavigationSnapshot, centre: Point) {
        val radius = snapshot.state.horizontalUncertaintyM?.takeIf { it.isFinite() && it > 0.0 }
        val features = if (radius == null) emptyArray() else {
            val latitude = centre.latitude()
            val lonScale = (111_320.0 * cos(latitude * PI / 180.0)).coerceAtLeast(1.0)
            val ring = True3dUncertaintyPolicy.ring(radius).map { offset ->
                Point.fromLngLat(centre.longitude() + offset.eastM / lonScale, latitude + offset.northM / 110_574.0)
            }
            arrayOf(Feature.fromGeometry(Polygon.fromLngLats(listOf(ring))))
        }
        activeStyle.getSourceAs<GeoJsonSource>(UNCERTAINTY_SOURCE)?.setGeoJson(FeatureCollection.fromFeatures(features))
        val color = colorHex(MapStateStyle.color(snapshot.state.localizationMode))
        activeStyle.getLayerAs<FillLayer>(UNCERTAINTY_LAYER)?.setProperties(
            PropertyFactory.fillColor(color), PropertyFactory.fillOutlineColor(color),
        )
    }

    private fun historySource(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE -> HISTORY_IDR_SOURCE
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> HISTORY_RECOVERY_SOURCE
        else -> HISTORY_GNSS_SOURCE
    }

    private fun markerImage(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE -> MARKER_IDR_IMAGE
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> MARKER_RECOVERY_IMAGE
        LocalizationMode.ERROR -> MARKER_ERROR_IMAGE
        LocalizationMode.GNSS_ACTIVE -> MARKER_GNSS_IMAGE
        else -> MARKER_NEUTRAL_IMAGE
    }

    private fun markerBitmap(color: Int): Bitmap {
        val density = resources.displayMetrics.density
        val size = (64 * density).toInt().coerceAtLeast(64)
        return Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888).also { bitmap ->
            val canvas = Canvas(bitmap); canvas.scale(size / 64f, size / 64f)
            val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = (color and 0x00FFFFFF) or (72 shl 24) }
            canvas.drawCircle(32f, 36f, 27f, halo)
            val path = Path().apply { moveTo(32f, 5f); lineTo(55f, 55f); lineTo(32f, 44f); lineTo(9f, 55f); close() }
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeJoin = Paint.Join.ROUND; style = Paint.Style.FILL; this.color = color }
            canvas.drawPath(path, paint)
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 5f; paint.color = Color.rgb(7, 19, 31); canvas.drawPath(path, paint)
            paint.strokeWidth = 1.5f; paint.color = Color.WHITE; canvas.drawPath(path, paint)
        }
    }

    private fun fail(detail: String) {
        failed = true; ready = false
        publish(MapPresentation(PROVIDER_ID, MapAvailability.NETWORK_UNAVAILABLE, "TRUE 3D UNAVAILABLE", detail, ATTRIBUTION))
    }

    private fun publish(value: MapPresentation) { presentation = value; onStatus(value) }
    private fun updateCameraInsets(w: Int, h: Int) {
        // Keep the engine position above the bottom telemetry panel without pushing it below
        // an oversized top inset.  Insets alter only the optical centre, never coordinates.
        if (w > 0 && h > 0) map?.setPadding(0, (h * 0.07).toInt(), 0, (h * 0.19).toInt())
    }
    private fun validCoordinate(lat: Double, lon: Double) = lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0
    private fun colorHex(color: Int) = String.format("#%06X", color and 0xFFFFFF)

    companion object {
        const val STYLE_URI = "https://tiles.openfreemap.org/styles/bright"
        const val ATTRIBUTION = "OpenFreeMap • © OpenStreetMap contributors"
        private const val PROVIDER_ID = "maplibre_openfreemap_3d"
        private const val OPEN_MAP_SOURCE = "openmaptiles"
        private const val BUILDING_SOURCE_LAYER = "building"
        private const val BUILDING_LAYER = "navghost-buildings-3d"
        private const val MARKER_SOURCE = "navghost-marker-source"
        private const val MARKER_LAYER = "navghost-marker-layer"
        private const val MARKER_GNSS_IMAGE = "navghost-marker-gnss"
        private const val MARKER_IDR_IMAGE = "navghost-marker-idr"
        private const val MARKER_RECOVERY_IMAGE = "navghost-marker-recovery"
        private const val MARKER_ERROR_IMAGE = "navghost-marker-error"
        private const val MARKER_NEUTRAL_IMAGE = "navghost-marker-neutral"
        private const val UNCERTAINTY_SOURCE = "navghost-uncertainty-source"
        private const val UNCERTAINTY_LAYER = "navghost-uncertainty-layer"
        private const val HISTORY_GNSS_SOURCE = "navghost-history-gnss-source"
        private const val HISTORY_IDR_SOURCE = "navghost-history-idr-source"
        private const val HISTORY_RECOVERY_SOURCE = "navghost-history-recovery-source"
        private const val HISTORY_GNSS_LAYER = "navghost-history-gnss-layer"
        private const val HISTORY_IDR_LAYER = "navghost-history-idr-layer"
        private const val HISTORY_RECOVERY_LAYER = "navghost-history-recovery-layer"
        private const val CAMERA_DURATION_MS = 140
    }
}
