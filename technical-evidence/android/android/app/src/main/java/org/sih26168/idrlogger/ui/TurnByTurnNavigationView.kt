package org.sih26168.idrlogger.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.GoogleMap
import com.google.android.gms.maps.MapView
import com.google.android.gms.maps.OnMapReadyCallback
import com.google.android.gms.maps.model.BitmapDescriptorFactory
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.LatLngBounds
import com.google.android.gms.maps.model.Marker
import com.google.android.gms.maps.model.MarkerOptions
import com.google.android.gms.maps.model.Polyline
import com.google.android.gms.maps.model.PolylineOptions
import java.util.Locale
import kotlin.math.max
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.R
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.map.EngineMarkerPolicy
import org.sih26168.idrlogger.map.MapCameraPolicy
import org.sih26168.idrlogger.map.FollowResumeGuard
import org.sih26168.idrlogger.product.AndroidApiIdentity
import org.sih26168.idrlogger.product.DestinationSearchClient
import org.sih26168.idrlogger.product.DroppedPinDestination
import org.sih26168.idrlogger.product.NavigationRoute
import org.sih26168.idrlogger.product.RouteDestination
import org.sih26168.idrlogger.product.RouteDirectionsClient
import org.sih26168.idrlogger.product.RoutePoint
import org.sih26168.idrlogger.product.RouteProgressTracker

/**
 * Normal road-navigation surface. The map, route and speech are presentation-only: the current
 * marker is always copied from NavigationSnapshot and Google location/blue-dot APIs stay disabled.
 */
class TurnByTurnNavigationView(
    context: Context,
    savedState: Bundle?,
    private val snapshotProvider: () -> NavigationSnapshot,
    private val onStartNavGhost: () -> Unit,
) : FrameLayout(context), OnMapReadyCallback, TextToSpeech.OnInitListener {
    private val mapView = MapView(context)
    private val identity = AndroidApiIdentity.from(context)
    private val searchClient = DestinationSearchClient(BuildConfig.PLACES_API_KEY, androidPackage = identity.packageName, androidCertSha1 = identity.certificateSha1)
    private val routeClient = RouteDirectionsClient()
    private val uiHandler = Handler(Looper.getMainLooper())
    private val searchField: EditText
    private val resultsPanel: LinearLayout
    private val instruction: TextView
    private val routeSummary: TextView
    private val sourceStatus: TextView
    private val voiceButton: Button
    private val recenterButton: Button
    private var googleMap: GoogleMap? = null
    private var currentMarker: Marker? = null
    private var destinationMarker: Marker? = null
    private var routeLine: Polyline? = null
    private var route: NavigationRoute? = null
    private var progressTracker: RouteProgressTracker? = null
    private var destination: RouteDestination? = null
    private val cameraPolicy = MapCameraPolicy(minimumUpdateIntervalMs = 250L)
    private val followResumeGuard = FollowResumeGuard()
    private var satellite = false
    private var routing = false
    private var voiceEnabled = true
    private var ttsReady = false
    private var pendingSpeech: String? = null
    private var tts: TextToSpeech? = null
    private var lastRerouteMs = Long.MIN_VALUE
    private var offRouteSamples = 0
    private var searchGeneration = 0L
    private var suppressSuggestions = false
    private var pendingSuggestionQuery = ""
    private val suggestionSearch = Runnable { performSearch(pendingSuggestionQuery, manual = false) }

    init {
        setBackgroundColor(BACKGROUND)
        mapView.onCreate(savedState)
        mapView.getMapAsync(this)
        addView(mapView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))

        val top = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(10), dp(10), dp(10))
            background = rounded(Color.argb(244, 7, 18, 30), 18f, BORDER)
        }
        val searchRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        searchField = EditText(context).apply {
            hint = "Where do you want to go?"
            setHintTextColor(MUTED)
            setTextColor(TEXT)
            textSize = 15f
            setSingleLine(true)
            imeOptions = EditorInfo.IME_ACTION_SEARCH
            backgroundTintList = ColorStateList.valueOf(ACCENT)
            setOnEditorActionListener { _, action, _ -> if (action == EditorInfo.IME_ACTION_SEARCH) { search(); true } else false }
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(value: CharSequence?, start: Int, count: Int, after: Int) = Unit
                override fun onTextChanged(value: CharSequence?, start: Int, before: Int, count: Int) = Unit
                override fun afterTextChanged(value: Editable?) {
                    if (suppressSuggestions) return
                    uiHandler.removeCallbacks(suggestionSearch)
                    pendingSuggestionQuery = value?.toString()?.trim().orEmpty()
                    if (pendingSuggestionQuery.length >= 2) {
                        uiHandler.postDelayed(suggestionSearch, SUGGESTION_DELAY_MS)
                    } else {
                        searchGeneration += 1
                        resultsPanel.removeAllViews()
                        resultsPanel.visibility = View.GONE
                        if (destination == null) instruction.text = "Type a destination to see suggestions"
                    }
                }
            })
        }
        searchRow.addView(searchField, LinearLayout.LayoutParams(0, dp(50), 1f))
        searchRow.addView(button("GO") { search() }, LinearLayout.LayoutParams(dp(72), dp(48)).apply { marginStart = dp(8) })
        top.addView(searchRow)
        resultsPanel = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        top.addView(resultsPanel)
        instruction = label("Search for a destination to begin", 18f, TEXT, true)
        instruction.setPadding(0, dp(8), 0, 0)
        top.addView(instruction)
        sourceStatus = label("POSITION • NAVGHOST ENGINE", 10f, ACCENT, true)
        top.addView(sourceStatus)
        addView(top, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, Gravity.TOP).apply { setMargins(dp(8), dp(8), dp(8), 0) })

        val right = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        recenterButton = button("FOLLOWING") {
            followResumeGuard.invalidate()
            cameraPolicy.recenter()
            updateFollowButton()
            update(snapshotProvider(), forceCamera = true)
        }
        val mapType = button("MAP") {
            satellite = !satellite
            googleMap?.mapType = if (satellite) GoogleMap.MAP_TYPE_HYBRID else GoogleMap.MAP_TYPE_NORMAL
            (it as? Button)?.text = if (satellite) "HYBRID" else "MAP"
        }
        right.addView(recenterButton, LinearLayout.LayoutParams(dp(92), dp(48)).apply { bottomMargin = dp(6) })
        right.addView(mapType, LinearLayout.LayoutParams(dp(92), dp(48)))
        addView(right, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL or Gravity.END).apply { marginEnd = dp(10) })

        val bottom = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = rounded(Color.argb(244, 7, 18, 30), 18f, BORDER)
        }
        routeSummary = label("ONLINE ROAD ROUTING • VOICE READY", 13f, SECONDARY, true)
        bottom.addView(routeSummary)
        val controls = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        voiceButton = button("VOICE • ON") { voiceEnabled = !voiceEnabled; voiceButton.text = "VOICE • ${if (voiceEnabled) "ON" else "OFF"}"; if (!voiceEnabled) tts?.stop() }
        controls.addView(voiceButton, LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginEnd = dp(4) })
        controls.addView(button("START IDR") { onStartNavGhost() }, LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginStart = dp(4); marginEnd = dp(4) })
        controls.addView(button("END ROUTE") { clearRoute() }, LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginStart = dp(4) })
        bottom.addView(controls, LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dp(48)).apply { topMargin = dp(8) })
        bottom.addView(label("Route data © OpenStreetMap contributors • GPS/IDR position remains NavGhost", 9f, MUTED), LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { topMargin = dp(6) })
        addView(bottom, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT, Gravity.BOTTOM).apply { setMargins(dp(8), 0, dp(8), dp(8)) })

        tts = TextToSpeech(context.applicationContext, this)
    }

    override fun onMapReady(map: GoogleMap) {
        googleMap = map
        map.mapType = GoogleMap.MAP_TYPE_NORMAL
        map.isBuildingsEnabled = true
        map.isTrafficEnabled = true
        map.uiSettings.apply {
            isCompassEnabled = true
            isZoomControlsEnabled = false
            isMapToolbarEnabled = false
            isMyLocationButtonEnabled = false
            isRotateGesturesEnabled = true
            isTiltGesturesEnabled = true
        }
        map.setPadding(0, dp(112), 0, dp(126))
        map.setOnCameraMoveStartedListener { reason ->
            if (reason == GoogleMap.OnCameraMoveStartedListener.REASON_GESTURE) {
                followResumeGuard.invalidate()
                map.stopAnimation()
                cameraPolicy.onUserGesture()
                updateFollowButton()
            }
        }
        map.setOnMapLongClickListener { point -> navigateToDroppedPin(point.latitude, point.longitude) }
        map.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(20.5937, 78.9629), 4.6f))
        update(snapshotProvider(), forceCamera = true)
    }

    fun update(snapshot: NavigationSnapshot, forceCamera: Boolean = false) {
        val map = googleMap ?: return
        val state = snapshot.state
        val lat = state.latitudeDeg
        val lon = state.longitudeDeg
        if (lat == null || lon == null || !lat.isFinite() || !lon.isFinite()) {
            currentMarker?.isVisible = false
            sourceStatus.text = "POSITION • WAITING FOR NAVGHOST FIX"
            return
        }
        val position = LatLng(lat, lon)
        sourceStatus.text = "POSITION • NAVGHOST ENGINE • ${state.localizationMode.name.replace('_', ' ')}"
        currentMarker = currentMarker ?: map.addMarker(MarkerOptions().position(position).title("NavGhost position")
            .flat(true).anchor(0.5f, 0.66f).icon(vehicleIcon()).zIndex(20f))
        currentMarker?.isVisible = true
        currentMarker?.position = position
        if (state.headingDeg.isFinite()) currentMarker?.rotation = state.headingDeg.toFloat()
        destination?.let { selected -> if (route == null && !routing) requestRoute(selected, RoutePoint(lat, lon)) }
        progressTracker?.let { tracker ->
            val progress = tracker.update(RoutePoint(lat, lon), state.speedMps, state.horizontalUncertaintyM)
            instruction.text = if (progress.arrived) "ARRIVED" else formatDistance(progress.distanceToManeuverM) + " • " + progress.instruction
            if (progress.shouldSpeak) speak(progress.instruction)
            val threshold = max(65.0, (state.horizontalUncertaintyM ?: 0.0) * 2.0)
            offRouteSamples = if (progress.offRouteDistanceM > threshold) offRouteSamples + 1 else 0
            val now = SystemClock.elapsedRealtime()
            if (offRouteSamples >= 3 && (lastRerouteMs == Long.MIN_VALUE || now - lastRerouteMs >= REROUTE_COOLDOWN_MS)) {
                lastRerouteMs = now; offRouteSamples = 0
                destination?.let { requestRoute(it, RoutePoint(lat, lon), rerouting = true) }
            }
        }
        val now = SystemClock.elapsedRealtime()
        if (forceCamera) cameraPolicy.recenter()
        if (forceCamera || cameraPolicy.shouldUpdate(now)) {
            val frame = cameraPolicy.frame(
                EngineMarkerPolicy.from(snapshot),
                state.speedMps,
                state.motionState,
                state.localizationMode,
                state.confidence == ConfidenceLevel.HIGH || state.confidence == ConfidenceLevel.MEDIUM,
            )
            if (frame != null) {
                map.animateCamera(CameraUpdateFactory.newCameraPosition(com.google.android.gms.maps.model.CameraPosition.Builder()
                    .target(LatLng(frame.target.latitudeDeg, frame.target.longitudeDeg))
                    .zoom(frame.zoom).bearing(frame.bearingDeg).tilt(frame.tiltDeg).build()), CAMERA_ANIMATION_MS, null)
            }
        }
    }

    private fun search() {
        val query = searchField.text.toString().trim()
        if (query.length < 2) { Toast.makeText(context, "Enter a destination", Toast.LENGTH_SHORT).show(); return }
        performSearch(query, manual = true)
    }

    private fun performSearch(query: String, manual: Boolean) {
        if (query.length < 2) return
        uiHandler.removeCallbacks(suggestionSearch)
        val generation = ++searchGeneration
        if (manual) {
            searchField.clearFocus()
            (context.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)
                ?.hideSoftInputFromWindow(searchField.windowToken, 0)
        }
        instruction.text = if (manual) "Searching destinations…" else "Finding nearby matches…"
        resultsPanel.removeAllViews(); resultsPanel.visibility = View.GONE
        val state = snapshotProvider().state
        val bias = if (state.latitudeDeg != null && state.longitudeDeg != null) RoutePoint(state.latitudeDeg, state.longitudeDeg) else null
        searchClient.search(query, bias) { result -> post {
            if (generation != searchGeneration || query != searchField.text.toString().trim()) return@post
            result.fold(::showSearchResults) { error -> instruction.text = "Search unavailable • ${error.message ?: "check internet"}" }
        } }
    }

    private fun showSearchResults(results: List<RouteDestination>) {
        resultsPanel.removeAllViews()
        if (results.isEmpty()) { instruction.text = "No destination found"; resultsPanel.visibility = View.GONE; return }
        instruction.text = "Choose a destination"
        results.take(4).forEach { item ->
            val row = button("${item.name}\n${item.address}") { chooseDestination(item) }.apply {
                gravity = Gravity.START or Gravity.CENTER_VERTICAL
                textSize = 12f
                maxLines = 2
            }
            resultsPanel.addView(row, LinearLayout.LayoutParams(LayoutParams.MATCH_PARENT, dp(58)).apply { topMargin = dp(4) })
        }
        resultsPanel.visibility = View.VISIBLE
    }

    private fun chooseDestination(value: RouteDestination) {
        uiHandler.removeCallbacks(suggestionSearch)
        searchGeneration += 1
        suppressSuggestions = true
        searchField.setText(value.name)
        searchField.setSelection(searchField.text.length)
        suppressSuggestions = false
        destination = value
        route = null
        progressTracker = null
        resultsPanel.visibility = View.GONE
        instruction.text = "Preparing route to ${value.name}…"
        val state = snapshotProvider().state
        val lat = state.latitudeDeg; val lon = state.longitudeDeg
        if (lat == null || lon == null) {
            instruction.text = "Start NavGhost and wait for a position to calculate the route"
            onStartNavGhost()
        } else requestRoute(value, RoutePoint(lat, lon))
    }

    fun navigateToDroppedPin(latitude: Double, longitude: Double) {
        val selected = DroppedPinDestination.create(latitude, longitude) ?: run {
            Toast.makeText(context, "That map point is not a valid destination", Toast.LENGTH_SHORT).show()
            return
        }
        Toast.makeText(context, "Dropped pin selected", Toast.LENGTH_SHORT).show()
        chooseDestination(selected)
    }

    private fun requestRoute(value: RouteDestination, origin: RoutePoint, rerouting: Boolean = false) {
        if (routing) return
        routing = true
        instruction.text = if (rerouting) "Off route • recalculating…" else "Calculating the fastest driving route…"
        routeClient.route(origin, RoutePoint(value.latitudeDeg, value.longitudeDeg)) { result -> post {
            routing = false
            result.fold({ renderRoute(value, it, rerouting) }) { error ->
                instruction.text = "Route unavailable • ${error.message ?: "check internet"}"
                routeSummary.text = "SEARCH WORKS OFF THE ESTIMATOR • ROUTING NEEDS INTERNET"
            }
        } }
    }

    private fun renderRoute(value: RouteDestination, valueRoute: NavigationRoute, rerouting: Boolean) {
        val map = googleMap ?: return
        route = valueRoute
        progressTracker = RouteProgressTracker(valueRoute)
        routeLine?.remove()
        routeLine = map.addPolyline(PolylineOptions().addAll(valueRoute.points.map { LatLng(it.latitudeDeg, it.longitudeDeg) })
            .color(ROUTE).width(dp(7).toFloat()).zIndex(10f).geodesic(true))
        destinationMarker?.remove()
        destinationMarker = map.addMarker(MarkerOptions().position(LatLng(value.latitudeDeg, value.longitudeDeg)).title(value.name)
            .icon(BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_ROSE)).zIndex(18f))
        val minutes = (valueRoute.durationSeconds / 60.0).toInt().coerceAtLeast(1)
        routeSummary.text = "${formatDistance(valueRoute.distanceM)} • ~$minutes min • ${value.name}"
        instruction.text = valueRoute.steps.firstOrNull()?.instruction ?: "Follow the highlighted route"
        if (!rerouting) speak("Route started. ${instruction.text}") else speak("Route recalculated. ${instruction.text}")
        val bounds = LatLngBounds.Builder().also { builder -> valueRoute.points.forEach { builder.include(LatLng(it.latitudeDeg, it.longitudeDeg)) } }.build()
        val resumeToken = followResumeGuard.token()
        val resumeFollow = cameraPolicy.following
        map.animateCamera(CameraUpdateFactory.newLatLngBounds(bounds, dp(64)), 650, null)
        postDelayed({
            if (!resumeFollow || !cameraPolicy.following || !followResumeGuard.isCurrent(resumeToken)) return@postDelayed
            cameraPolicy.recenter()
            updateFollowButton()
            update(snapshotProvider(), forceCamera = true)
        }, 900L)
    }

    private fun clearRoute() {
        followResumeGuard.invalidate()
        route = null; progressTracker = null; destination = null; offRouteSamples = 0
        routeLine?.remove(); routeLine = null
        destinationMarker?.remove(); destinationMarker = null
        tts?.stop()
        instruction.text = "Search for a destination to begin"
        routeSummary.text = "ONLINE ROAD ROUTING • VOICE READY"
    }

    private fun speak(text: String) {
        if (!voiceEnabled) return
        if (!ttsReady) { pendingSpeech = text; return }
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "navghost-${SystemClock.elapsedRealtime()}")
    }

    private fun updateFollowButton() {
        recenterButton.text = if (cameraPolicy.following) "FOLLOWING" else "RECENTER"
    }

    override fun onInit(status: Int) {
        ttsReady = status == TextToSpeech.SUCCESS
        if (ttsReady) {
            tts?.language = Locale.US
            pendingSpeech?.let { pendingSpeech = null; speak(it) }
        } else voiceButton.text = "VOICE • UNAVAILABLE"
    }

    fun onStart() = mapView.onStart()
    fun onResume() = mapView.onResume()
    fun onPause() = mapView.onPause()
    fun onStop() = mapView.onStop()
    fun onLowMemory() = mapView.onLowMemory()
    fun onSaveInstanceState(out: Bundle) = mapView.onSaveInstanceState(out)
    fun onDestroy() {
        uiHandler.removeCallbacksAndMessages(null)
        tts?.stop(); tts?.shutdown()
        searchClient.close(); routeClient.close()
        mapView.onDestroy()
    }

    private fun button(value: String, action: (View) -> Unit) = Button(context).apply {
        text = value; textSize = 11f; setTextColor(TEXT); isAllCaps = false
        backgroundTintList = ColorStateList.valueOf(SURFACE)
        setOnClickListener(action)
    }
    private fun label(value: String, size: Float, color: Int, bold: Boolean = false) = TextView(context).apply {
        text = value; textSize = size; setTextColor(color); if (bold) setTypeface(typeface, Typeface.BOLD)
    }
    private fun rounded(color: Int, radius: Float, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(radius.toInt()).toFloat(); stroke?.let { setStroke(dp(1), it) }
    }
    private fun formatDistance(metres: Double): String = if (metres >= 1000.0) String.format(Locale.US, "%.1f km", metres / 1000.0) else "${metres.toInt().coerceAtLeast(0)} m"
    private fun vehicleIcon() = BitmapDescriptorFactory.fromBitmap(Bitmap.createBitmap(dp(28), dp(28), Bitmap.Config.ARGB_8888).also { bitmap ->
        context.getDrawable(R.drawable.navghost_vehicle_arrow)?.apply {
            setBounds(0, 0, bitmap.width, bitmap.height)
            draw(Canvas(bitmap))
        }
    })
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val REROUTE_COOLDOWN_MS = 20_000L
        private const val SUGGESTION_DELAY_MS = 450L
        private const val CAMERA_ANIMATION_MS = 180
        private val BACKGROUND = Color.rgb(5, 13, 22)
        private val SURFACE = Color.rgb(20, 42, 59)
        private val BORDER = Color.rgb(52, 77, 96)
        private val TEXT = Color.rgb(245, 249, 252)
        private val SECONDARY = Color.rgb(190, 207, 220)
        private val MUTED = Color.rgb(139, 161, 179)
        private val ACCENT = Color.rgb(74, 216, 181)
        private val ROUTE = Color.rgb(30, 136, 255)
    }
}
