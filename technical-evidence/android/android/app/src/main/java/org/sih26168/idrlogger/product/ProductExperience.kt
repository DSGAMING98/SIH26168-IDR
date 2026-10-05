package org.sih26168.idrlogger.product

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.text.DateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.hypot
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.model.LoggerStatus
import org.sih26168.idrlogger.ui.UiSemantics

class ProductExperience(
    private val activity: Activity,
    private val dark: Boolean,
    private val snapshot: () -> NavigationSnapshot,
    private val loggerStatus: () -> LoggerStatus?,
    private val rendererLabel: () -> String,
    private val onToggleNavigation: () -> Unit,
    private val onOpenMap: () -> Unit,
    private val onOpenDemo: () -> Unit,
    private val onOpenEngineering: () -> Unit,
    private val onExportDirectory: (File) -> Unit,
) {
    private val repository = TripRepository(activity)
    private val nearbyIdentity = AndroidApiIdentity.from(activity)
    private val nearby = NearbyPlacesClient(BuildConfig.PLACES_API_KEY, androidPackage = nearbyIdentity.packageName, androidCertSha1 = nearbyIdentity.certificateSha1)
    private var trips: List<TripEntity> = emptyList()
    private var lastRefreshMs = 0L

    private lateinit var dashboardStatus: TextView
    private lateinit var dashboardCurrent: TextView
    private lateinit var dashboardTotals: TextView
    private lateinit var dashboardAction: Button
    private lateinit var nearbyAnchor: TextView
    private lateinit var nearbyResults: LinearLayout
    private lateinit var nearbyQuery: EditText
    private lateinit var historyList: LinearLayout
    private lateinit var insightsTotals: TextView
    private lateinit var insightsReliability: TextView
    private lateinit var insightsChart: MiniChartView
    private lateinit var insightSpeedChart: MiniChartView
    private lateinit var insightUncertaintyChart: MiniChartView
    private lateinit var insightHeadingChart: MiniChartView
    private lateinit var insightModeChart: MiniChartView

    val dashboardView: View by lazy(::buildDashboard)
    val nearbyView: View by lazy(::buildNearby)
    val historyView: View by lazy(::buildHistory)
    val insightsView: View by lazy(::buildInsights)

    fun updateDashboard() {
        if (!::dashboardStatus.isInitialized) return
        val nav = snapshot().state
        val status = loggerStatus()
        dashboardStatus.text = when {
            status?.recording != true -> "READY TO NAVIGATE"
            nav.localizationMode == LocalizationMode.IDR_ACTIVE -> "GNSS LOST • NAVGHOST ACTIVE"
            nav.localizationMode == LocalizationMode.GNSS_VERIFYING -> "SIGNAL RETURNED • VERIFYING"
            nav.localizationMode == LocalizationMode.GNSS_RECOVERING -> "SMOOTHLY RECOVERING"
            nav.localizationMode == LocalizationMode.GNSS_ACTIVE -> "NAVIGATION ACTIVE"
            else -> UiSemantics.localizationLabel(nav.localizationMode)
        }
        dashboardAction.text = if (status?.recording == true) "STOP NAVIGATION" else "START NAVIGATION"
        val distance = snapshot().trajectory.zipWithNext().sumOf { (a, b) -> hypot(b.eastM - a.eastM, b.northM - a.northM) }
        dashboardCurrent.text = String.format(Locale.US,
            "%.1f km/h\nCURRENT SPEED     •     %.2f km TRIP\n%s     •     %s\n%s",
            nav.speedMps.coerceAtLeast(0.0) * 3.6, distance / 1000.0,
            nav.horizontalUncertaintyM?.let { "± %.1f m confidence".format(Locale.US, it) } ?: "Confidence pending",
            rendererLabel(), safetyMessage(nav.localizationMode))
        val summary = InsightsCalculator.calculate(trips)
        dashboardTotals.text = String.format(Locale.US, "TODAY / SAVED TRIPS\n%d trips     •     %.1f km     •     %.0f min\n%.1f km/h average     •     %d GNSS-loss events",
            summary.tripCount, summary.totalDistanceM / 1000.0, summary.totalDurationSeconds / 60.0,
            summary.averageSpeedMps * 3.6, summary.gnssLossEvents)
        refreshDataIfNeeded()
    }

    fun refreshHistory(force: Boolean = true) {
        if (!::historyList.isInitialized) return
        repository.trips { loaded -> activity.runOnUiThread {
            trips = loaded; renderHistory(); renderInsights(); updateDashboard()
            loaded.firstOrNull()?.let { latest -> repository.trip(latest.id) { _, samples -> activity.runOnUiThread { renderRecentCharts(samples) } } }
        } }
        if (force) lastRefreshMs = System.currentTimeMillis()
    }

    fun updateNearbyAnchor() {
        if (!::nearbyAnchor.isInitialized) return
        nearbyAnchor.text = when (val result = NearbyQueryFactory.from(snapshot())) {
            is NearbyQueryResult.Ready -> String.format(Locale.US, "Searching from NavGhost estimate • %.5f, %.5f", result.anchor.latitudeDeg, result.anchor.longitudeDeg)
            is NearbyQueryResult.Unavailable -> result.reason
        }
    }

    private fun buildDashboard(): View = scroll {
        addView(title("DASHBOARD", "Your navigation at a glance"))
        dashboardStatus = label("READY TO NAVIGATE", 14f, ACCENT, true).apply { gravity = Gravity.CENTER; setPadding(dp(10), dp(12), dp(10), dp(12)); background = rounded(SURFACE_HIGH, 14f) }
        addView(dashboardStatus, lp(bottom = 9))
        dashboardCurrent = label("0 km/h\nCURRENT SPEED", 18f, PRIMARY_TEXT, true).apply { setLineSpacing(0f, 1.25f) }
        addView(card("LIVE JOURNEY", dashboardCurrent), lp(bottom = 9))
        dashboardTotals = label("No completed trips yet.", 14f, SECONDARY_TEXT).apply { setLineSpacing(0f, 1.25f) }
        addView(card("TRIP SUMMARY", dashboardTotals), lp(bottom = 9))
        addView(card("WHAT NAVGHOST IS DOING", label("GNSS available: phone sensors strengthen continuity.\nGNSS denied: on-device IDR continues with uncertainty.\nSignal returns: fixes are verified before smooth recovery.", 13f, SECONDARY_TEXT)), lp(bottom = 9))
        dashboardAction = action("START NAVIGATION") { onToggleNavigation() }
        addView(dashboardAction, lp(52, 5))
        val quick = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
        quick.addView(secondary("OPEN MAP") { onOpenMap() }, weight())
        quick.addView(secondary("JUDGE DEMO") { onOpenDemo() }, weight())
        quick.addView(secondary("ENGINEERING") { onOpenEngineering() }, weight())
        addView(quick, lp(50, 18))
    }

    private fun buildNearby(): View = scroll {
        addView(title("NEARBY", "${nearby.providerName} • from NavGhost's current estimate"))
        nearbyAnchor = label("Start navigation and wait for a position.", 12f, SECONDARY_TEXT)
        addView(card("SEARCH ORIGIN", nearbyAnchor), lp(bottom = 8))
        nearbyQuery = EditText(activity).apply {
            hint = "Search a place by name (for example, cafe)"
            setTextColor(PRIMARY_TEXT); setHintTextColor(MUTED); isSingleLine = true
            backgroundTintList = ColorStateList.valueOf(ACCENT)
        }
        addView(nearbyQuery, lp(50, 8))
        addView(action("SEARCH BY NAME") { runNearbySearch(NearbyPlacesClient.SEARCH_ALL_CATEGORY) }, lp(48, 8))
        addView(label("Or choose a category", 11f, ACCENT, true), lp(bottom = 4))
        val categories = listOf("⛽" to "gas_station", "🅿" to "parking", "🏥" to "hospital", "₹" to "atm",
            "🔧" to "car_repair", "⚡" to "electric_vehicle_charging_station", "✚" to "pharmacy", "★" to "police", "🍴" to "restaurant")
        val grid = GridLayout(activity).apply { columnCount = 4 }
        categories.forEach { (icon, type) ->
            val name = type.replace('_', ' ').uppercase(Locale.US)
            grid.addView(secondary("$icon\n$name") { runNearbySearch(type) }, GridLayout.LayoutParams().apply { width = 0; height = dp(68); columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f); setMargins(dp(2), dp(2), dp(2), dp(2)) })
        }
        addView(grid, lp(bottom = 8))
        addView(label("Nearby uses live place data around the current NavGhost estimate. It requires internet, but localization continues if every provider is unavailable.", 11f, MUTED), lp(bottom = 8))
        nearbyResults = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL }
        addView(nearbyResults, lp(bottom = 18))
        updateNearbyAnchor()
    }

    private fun runNearbySearch(category: String) {
        val origin = NearbyQueryFactory.from(snapshot())
        if (origin is NearbyQueryResult.Unavailable) { showNearbyMessage(origin.reason); return }
        origin as NearbyQueryResult.Ready
        if (category == NearbyPlacesClient.SEARCH_ALL_CATEGORY && nearbyQuery.text.toString().trim().length < 2) {
            showNearbyMessage("Enter at least two letters, then tap SEARCH BY NAME.")
            return
        }
        showNearbyMessage("Searching live nearby data…")
        nearby.search(origin.anchor, category, nearbyQuery.text.toString()) { result -> activity.runOnUiThread {
            result.fold(::renderNearbyResults) { error ->
                val message = if (error.message?.startsWith("Please wait") == true) error.message!!
                else "Could not reach nearby data providers. Check internet and retry.\nNavGhost localization remains active."
                showNearbyMessage(message)
            }
        } }
    }

    private fun showNearbyMessage(message: String) {
        nearbyResults.removeAllViews(); nearbyResults.addView(card("NEARBY STATUS", label(message, 13f, SECONDARY_TEXT)))
    }

    private fun renderNearbyResults(results: List<NearbyPlace>) {
        nearbyResults.removeAllViews()
        if (results.isEmpty()) { showNearbyMessage("No matching places were returned for this area."); return }
        results.forEach { place ->
            val details = String.format(Locale.US, "%s • %.0f m%s", place.category, place.distanceM,
                place.rating?.let { " • ★ %.1f".format(Locale.US, it) } ?: "")
            nearbyResults.addView(card(place.name, label(details, 12f, SECONDARY_TEXT), secondary("NAVIGATE • VOICE") {
                chooseDirectionsMode(place)
            }), lp(bottom = 6))
        }
        nearbyResults.addView(label("Place data • ${nearby.providerName}", 10f, MUTED), lp(bottom = 4))
    }

    private fun chooseDirectionsMode(place: NearbyPlace) {
        val modes = DirectionsTravelMode.entries
        val content = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(4), dp(18), dp(2))
            addView(label("Choose how you are travelling. Google Maps opens the live route and voice guidance; NavGhost remains isolated from the planned route.", 13f, SECONDARY_TEXT), lp(bottom = 10))
        }
        lateinit var dialog: AlertDialog
        modes.forEach { mode ->
            content.addView(action("${mode.label.uppercase(Locale.US)} • NAVIGATE") {
                dialog.dismiss()
                launchDirections(place, mode)
            }, lp(50, 6))
        }
        dialog = AlertDialog.Builder(activity)
            .setTitle("Navigate to ${place.name}")
            .setView(content)
            .setNegativeButton("CLOSE", null)
            .create()
        dialog.show()
    }

    private fun launchDirections(place: NearbyPlace, mode: DirectionsTravelMode) {
        val uri = Uri.parse(ExternalDirections.url(place.latitudeDeg, place.longitudeDeg, mode))
        val googleMaps = Intent(Intent.ACTION_VIEW, uri).setPackage("com.google.android.apps.maps")
        val launched = runCatching { activity.startActivity(googleMaps) }.isSuccess ||
            runCatching { activity.startActivity(Intent(Intent.ACTION_VIEW, uri)) }.isSuccess
        Toast.makeText(
            activity,
            if (launched) "Opening ${mode.label.lowercase(Locale.US)} directions with voice guidance"
            else "No compatible directions app or browser was found",
            Toast.LENGTH_LONG,
        ).show()
    }

    private fun buildHistory(): View = scroll {
        addView(title("TRIP HISTORY", "Real navigation sessions stored locally"))
        historyList = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL }
        addView(historyList, lp(bottom = 18)); refreshHistory()
    }

    private fun renderHistory() {
        if (!::historyList.isInitialized) return
        historyList.removeAllViews()
        if (trips.isEmpty()) {
            historyList.addView(card("NO TRIPS YET", label("Start and stop a live navigation session. NavGhost will save a compact summary and 1 Hz trajectory here.", 13f, SECONDARY_TEXT)))
            return
        }
        trips.forEach { trip ->
            val date = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(trip.startWallTimeMs))
            val body = label(String.format(Locale.US, "%s\n%.2f km • %.0f min • %.1f km/h avg\n%s → %s\n%s",
                date, trip.distanceM / 1000.0, trip.durationSeconds / 60.0, trip.averageSpeedMps * 3.6,
                TripMetricsAccumulator.coordinateLabel(trip.startLatitudeDeg, trip.startLongitudeDeg),
                TripMetricsAccumulator.coordinateLabel(trip.endLatitudeDeg, trip.endLongitudeDeg), trip.status), 13f, SECONDARY_TEXT)
            historyList.addView(card(trip.title, body, secondary("VIEW DETAILS") { showTripDetails(trip.id) }), lp(bottom = 7))
        }
    }

    private fun showTripDetails(id: Long) = repository.trip(id) { trip, samples -> activity.runOnUiThread {
        if (trip == null) return@runOnUiThread
        val content = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(6), dp(14), dp(8))
            addView(card("TRIP OVERVIEW", label(String.format(Locale.US,
                "DISTANCE    %.2f km\nDURATION    %.0f min\nAVERAGE     %.1f km/h\nMAXIMUM     %.1f km/h",
                trip.distanceM / 1000.0, trip.durationSeconds / 60.0,
                trip.averageSpeedMps * 3.6, trip.maximumSpeedMps * 3.6), 14f, PRIMARY_TEXT, true)), lp(bottom = 8))
            addView(card("GNSS RESILIENCE", label(String.format(Locale.US,
                "GNSS active    %.1f min\nIDR active     %.1f s\nLongest IDR    %.1f s\nSignal-loss events    %d\nML assist    %s",
                trip.gnssActiveDurationSeconds / 60.0, trip.idrDurationSeconds, trip.longestIdrIntervalSeconds,
                trip.gnssLossEvents, if (trip.gruAssistanceUsed) "Observed" else "Not observed"), 13f, SECONDARY_TEXT)), lp(bottom = 8))
            addView(card("UNCERTAINTY", label(
                "AVERAGE    ${trip.averageUncertaintyM?.let { "%.1f m".format(Locale.US, it) } ?: "Not available"}\n" +
                    "MAXIMUM    ${trip.maximumUncertaintyM?.let { "%.1f m".format(Locale.US, it) } ?: "Not available"}",
                13f, SECONDARY_TEXT)), lp(bottom = 8))
            val speedContent = LinearLayout(activity).apply {
                orientation = LinearLayout.VERTICAL
                if (samples.size >= 2) addView(MiniChartView(activity).apply { setSeries(samples.map { it.speedMps * 3.6 }) }, lp(130, 4))
                else addView(label("No movement samples were recorded for this session.", 13f, MUTED), lp(bottom = 4))
                addView(label("${samples.size} local trajectory samples • 1 Hz summary", 11f, MUTED))
            }
            addView(card("SPEED PROFILE", speedContent), lp(bottom = 8))
            addView(card("SESSION", label(
                "Renderer    ${trip.rendererUsed ?: "Not recorded"}\nApp version    ${trip.appVersion ?: "Not recorded"}\nRecording    ${if (trip.sessionDirectory == null) "No export linked" else "Ready to export"}",
                12f, SECONDARY_TEXT)), lp(bottom = 4))
        }
        AlertDialog.Builder(activity).setTitle(trip.title).setView(ScrollView(activity).apply { addView(content) })
            .setNeutralButton("DELETE") { _, _ -> confirmDelete(trip) }
            .setNegativeButton("EXPORT") { _, _ -> trip.sessionDirectory?.let { onExportDirectory(File(it)) } ?: Toast.makeText(activity, "No session export is linked", Toast.LENGTH_LONG).show() }
            .setPositiveButton("DONE", null).show()
    } }

    private fun confirmDelete(trip: TripEntity) {
        AlertDialog.Builder(activity).setTitle("Delete this trip?").setMessage("This removes the product summary and 1 Hz trajectory. The raw exported recording is not deleted.")
            .setNegativeButton("CANCEL", null).setPositiveButton("DELETE") { _, _ -> repository.delete(trip) { activity.runOnUiThread { refreshHistory() } } }.show()
    }

    private fun buildInsights(): View = scroll {
        addView(title("INSIGHTS", "Patterns from your locally stored trips"))
        insightsTotals = label("No trip data yet.", 15f, PRIMARY_TEXT, true)
        addView(card("TRAVEL OVERVIEW", insightsTotals), lp(bottom = 8))
        insightsChart = MiniChartView(activity)
        insightsChart.minimumHeight = dp(120)
        addView(card("DISTANCE BY TRIP", insightsChart), lp(190, 8))
        insightSpeedChart = MiniChartView(activity).apply { minimumHeight = dp(120) }
        insightUncertaintyChart = MiniChartView(activity).apply { minimumHeight = dp(120) }
        insightHeadingChart = MiniChartView(activity).apply { minimumHeight = dp(120) }
        insightModeChart = MiniChartView(activity).apply { minimumHeight = dp(90) }
        addView(card("LATEST TRIP • SPEED OVER TIME", insightSpeedChart), lp(bottom = 8))
        addView(card("LATEST TRIP • UNCERTAINTY OVER TIME", insightUncertaintyChart), lp(bottom = 8))
        addView(card("LATEST TRIP • HEADING OVER TIME", insightHeadingChart), lp(bottom = 8))
        addView(card("LATEST TRIP • GNSS / IDR TIMELINE", insightModeChart), lp(bottom = 8))
        insightsReliability = label("Complete a trip to see GNSS resilience insights.", 13f, SECONDARY_TEXT)
        addView(card("NAVIGATION RESILIENCE", insightsReliability), lp(bottom = 18)); refreshHistory()
    }

    private fun renderInsights() {
        if (!::insightsTotals.isInitialized) return
        val s = InsightsCalculator.calculate(trips)
        insightsTotals.text = String.format(Locale.US, "%d TRIPS     •     %.1f km\n%.1f h total     •     %.1f km/h average\n%.1f km/h maximum",
            s.tripCount, s.totalDistanceM / 1000.0, s.totalDurationSeconds / 3600.0, s.averageSpeedMps * 3.6, s.maximumSpeedMps * 3.6)
        insightsReliability.text = String.format(Locale.US, "%d GNSS-loss events\n%.1f minutes navigated with IDR support\nLongest trip %.1f km • longest IDR interval %.1f s\nAverage recorded uncertainty %s\n\nAll analytics remain on this phone.",
            s.gnssLossEvents, s.totalIdrSeconds / 60.0, s.longestTripDistanceM / 1000.0, s.longestIdrIntervalSeconds,
            s.averageUncertaintyM?.let { "%.1f m".format(Locale.US, it) } ?: "Not enough data")
        insightsChart.setSeries(trips.reversed().map { it.distanceM / 1000.0 })
    }

    private fun renderRecentCharts(samples: List<TripSampleEntity>) {
        if (!::insightSpeedChart.isInitialized) return
        insightSpeedChart.setSeries(samples.map { it.speedMps * 3.6 })
        insightUncertaintyChart.setSeries(samples.mapNotNull { it.uncertaintyM })
        insightHeadingChart.setSeries(samples.map { it.headingDeg })
        insightModeChart.setSeries(samples.map { if (it.localizationMode in TripMetricsAccumulator.IDR_MODES.map(LocalizationMode::name)) 1.0 else 0.0 }, Color.rgb(255,174,72))
    }

    private fun refreshDataIfNeeded() {
        val now = System.currentTimeMillis(); if (now - lastRefreshMs < 10_000L) return
        lastRefreshMs = now; refreshHistory(false)
    }

    private fun safetyMessage(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.IDR_ACTIVE -> "GNSS denied — inertial estimate active"
        LocalizationMode.GNSS_VERIFYING -> "GNSS signal detected — checking quality"
        LocalizationMode.GNSS_RECOVERING -> "Trusted fix — correcting smoothly"
        LocalizationMode.GNSS_ACTIVE -> "GNSS trusted — NavGhost monitoring"
        else -> "Waiting for safe navigation readiness"
    }

    private fun scroll(block: LinearLayout.() -> Unit): ScrollView = ScrollView(activity).apply {
        isFillViewport = true; addView(LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(10), 0, 0); block() })
    }
    private fun title(name: String, subtitle: String) = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; addView(label(name, 22f, PRIMARY_TEXT, true)); addView(label(subtitle, 12f, SECONDARY_TEXT), lp(bottom = 9)) }
    private fun card(title: String, body: View, action: View? = null) = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(12), dp(14), dp(12)); background = rounded(SURFACE, 15f, BORDER)
        addView(label(title, 12f, ACCENT, true)); addView(body, lp(bottom = if (action == null) 0 else 6)); action?.let { addView(it, lp(46)) }
    }
    private fun label(textValue: String, size: Float, color: Int, bold: Boolean = false) = TextView(activity).apply { text = textValue; textSize = size; setTextColor(color); if (bold) setTypeface(typeface, Typeface.BOLD) }
    private fun action(textValue: String, click: () -> Unit) = Button(activity).apply { text = textValue; textSize = 12f; setTextColor(Color.WHITE); backgroundTintList = ColorStateList.valueOf(Color.rgb(24,115,158)); setOnClickListener { click() } }
    private fun secondary(textValue: String, click: () -> Unit) = Button(activity).apply { text = textValue; textSize = 10f; setTextColor(PRIMARY_TEXT); backgroundTintList = ColorStateList.valueOf(SURFACE_HIGH); setOnClickListener { click() } }
    private fun rounded(fill: Int, radius: Float, stroke: Int? = null) = GradientDrawable().apply { setColor(fill); cornerRadius = dp(radius.toInt()).toFloat(); stroke?.let { setStroke(dp(1), it) } }
    private fun lp(height: Int = ViewGroup.LayoutParams.WRAP_CONTENT, bottom: Int = 0) = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, if (height < 0) height else dp(height)).apply { bottomMargin = dp(bottom) }
    private fun weight() = LinearLayout.LayoutParams(0, dp(50), 1f).apply { setMargins(dp(2), 0, dp(2), 0) }
    private fun dp(value: Int) = (value * activity.resources.displayMetrics.density).toInt()
    private val SURFACE get() = if (dark) Color.rgb(14,28,42) else Color.WHITE
    private val SURFACE_HIGH get() = if (dark) Color.rgb(25,43,59) else Color.rgb(221,235,241)
    private val BORDER get() = if (dark) Color.rgb(44,66,84) else Color.rgb(190,211,220)
    private val PRIMARY_TEXT get() = if (dark) Color.rgb(245,249,252) else Color.rgb(12,31,44)
    private val SECONDARY_TEXT get() = if (dark) Color.rgb(190,207,220) else Color.rgb(54,79,94)
    private val MUTED get() = if (dark) Color.rgb(139,161,179) else Color.rgb(91,113,126)
    private val ACCENT get() = if (dark) Color.rgb(74,216,181) else Color.rgb(8,127,145)
}
