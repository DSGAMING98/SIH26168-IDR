package org.sih26168.idrlogger.ui

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.view.HapticFeedbackConstants
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.FrameLayout
import android.widget.GridLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.text.format.Formatter
import java.io.File
import java.io.FileInputStream
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.demo.DemoController
import org.sih26168.idrlogger.demo.PublicBenchmarkFixture
import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.model.FieldTestPhase
import org.sih26168.idrlogger.model.FieldTestPreset
import org.sih26168.idrlogger.model.MountProfile
import org.sih26168.idrlogger.product.ProductExperience
import org.sih26168.idrlogger.product.ProductSettings
import org.sih26168.idrlogger.product.ProductSettingsRepository
import org.sih26168.idrlogger.service.SensorLoggingService
import org.sih26168.idrlogger.map.LocalEnuMapProvider
import org.sih26168.idrlogger.map.MapPresentation
import org.sih26168.idrlogger.telemetry.TelemetryConfig
import org.sih26168.idrlogger.telemetry.TelemetryConnectionState
import org.sih26168.idrlogger.telemetry.TelemetrySettings

class MainActivity : Activity() {
    private enum class Page { LIVE, NAVIGATION, DASHBOARD, NEARBY, HISTORY, INSIGHTS, DEMO, DIAGNOSTICS, SETTINGS }
    private enum class DemoMode { QUICK_SYNTHETIC, PUBLIC_BENCHMARK }
    private enum class DemoComparison { INTELLIGENT_IDR, RAW_DR, REFERENCE, SHOW_ALL }

    private var service: SensorLoggingService? = null
    private var bound = false
    private var pendingStart = false
    private var exportSource: File? = null
    private var currentPage = Page.LIVE
    private var selectedPreset = FieldTestPreset.MEDIUM
    private var selectedMount = MountProfile.DASHBOARD
    private var demoComparison = DemoComparison.INTELLIGENT_IDR
    private var demoMode = DemoMode.QUICK_SYNTHETIC
    private var mapPresentation: MapPresentation = LocalEnuMapProvider().presentation()
    private lateinit var root: LinearLayout
    private lateinit var liveScreen: View
    private lateinit var navigationScreen: View
    private lateinit var demoScreen: View
    private lateinit var diagnosticsScreen: View
    private lateinit var settingsScreen: View
    private lateinit var dashboardScreen: View
    private lateinit var nearbyScreen: View
    private lateinit var historyScreen: View
    private lateinit var insightsScreen: View
    private lateinit var productExperience: ProductExperience
    private lateinit var stateChip: TextView
    private lateinit var contextLabel: TextView
    private lateinit var recordingLabel: TextView
    private lateinit var liveTrajectory: NavGhostMapSurface
    private lateinit var turnByTurnNavigation: TurnByTurnNavigationView
    private lateinit var demoTrajectory: TrajectoryView
    private lateinit var speedHero: TextView
    private lateinit var modeHero: TextView
    private lateinit var uncertaintyHero: TextView
    private lateinit var liveSecondary: TextView
    private lateinit var satelliteHud: TextView
    private lateinit var mapContextHud: TextView
    private lateinit var recenterButton: Button
    private lateinit var liveMessage: TextView
    private lateinit var telemetryIndicator: TextView
    private lateinit var telemetryDetails: TextView
    private lateinit var telemetryEndpoint: EditText
    private lateinit var telemetryEnabled: Switch
    private lateinit var telemetryRateButton: Button
    private var telemetryRateHz = 5
    private lateinit var drTimer: TextView
    private lateinit var livePrimaryButton: Button
    private lateinit var fieldPanel: View
    private lateinit var mapOrientationButton: Button
    private lateinit var mapTypeButton: Button
    private lateinit var rendererSelectorButton: Button
    private lateinit var calibrationCard: LinearLayout
    private lateinit var calibrationTitle: TextView
    private lateinit var calibrationBody: TextView
    private lateinit var calibrationProgress: ProgressBar
    private lateinit var blackoutButton: Button
    private lateinit var presetButton: Button
    private lateinit var mountButton: Button
    private lateinit var fieldStartButton: Button
    private lateinit var fieldStatus: TextView
    private lateinit var demoPhaseLabel: TextView
    private lateinit var demoTimeline: TextView
    private lateinit var demoBanner: TextView
    private lateinit var demoMetrics: TextView
    private lateinit var demoStartButton: Button
    private lateinit var publicBenchmarkReplayButton: Button
    private lateinit var comparisonButton: Button
    private lateinit var demoModeButton: Button
    private lateinit var demoControls: GridLayout
    private lateinit var healthOverview: TextView
    private lateinit var themeButton: Button
    private lateinit var hapticsButton: Button
    private lateinit var settingsRendererButton: Button
    private lateinit var settingsCameraButton: Button
    private lateinit var settingsTrailButton: Button
    private lateinit var settingsUncertaintyButton: Button
    private lateinit var settingsPerformanceButton: Button
    private lateinit var storageLabel: TextView
    private lateinit var uiPreferences: NavGhostUiPreferences
    private lateinit var productSettingsRepository: ProductSettingsRepository
    private var productSettings = ProductSettings()
    private var visualTheme = VisualTheme.SYSTEM
    private var darkTheme = true
    private var hapticsEnabled = true
    private var lastLiveMode: LocalizationMode? = null
    private var themeChangePending = false
    private val navItems = mutableMapOf<Page, TextView>()
    private val diagnostics = mutableMapOf<String, TextView>()
    private var demoPhase = "DEMO READY — synthetic data only"
    private var latestDemo = NavigationSnapshot(isDemoReplay = true)
    private lateinit var demoController: DemoController
    private val uiHandler = Handler(Looper.getMainLooper())
    private var publicReplayIndex = PublicBenchmarkFixture.replay.intelligentIdr.size
    private var publicReplayRunning = false
    private var publicReplayHasCompleted = false
    private val publicReplayTick = object : Runnable {
        override fun run() {
            if (!publicReplayRunning || demoMode != DemoMode.PUBLIC_BENCHMARK) return
            publicReplayIndex = (publicReplayIndex + 1).coerceAtMost(PublicBenchmarkFixture.replay.intelligentIdr.size)
            updatePublicBenchmark()
            if (publicReplayIndex < PublicBenchmarkFixture.replay.intelligentIdr.size) {
                uiHandler.postDelayed(this, PUBLIC_REPLAY_INTERVAL_MS)
            } else {
                publicReplayRunning = false
                publicReplayHasCompleted = true
                publicBenchmarkReplayButton.text = "REPLAY PUBLIC BENCHMARK"
            }
        }
    }
    private val refresh = object : Runnable {
        override fun run() { updateUi(); uiHandler.postDelayed(this, HUD_REFRESH_INTERVAL_MS) }
    }
    private val mapRefresh = object : Runnable {
        override fun run() {
            updateLiveMap()
            updateNavigationMap()
            uiHandler.postDelayed(this, if (productSettings.performanceMode) PERFORMANCE_MAP_REFRESH_INTERVAL_MS else MAP_REFRESH_INTERVAL_MS)
        }
    }
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            service = (binder as SensorLoggingService.LocalBinder).service(); bound = true; updateUi(); updateLiveMap()
        }
        override fun onServiceDisconnected(name: ComponentName?) { service = null; bound = false }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        uiPreferences = NavGhostUiPreferences(this)
        productSettingsRepository = ProductSettingsRepository.create(this)
        visualTheme = uiPreferences.theme()
        hapticsEnabled = uiPreferences.hapticsEnabled()
        darkTheme = NavGhostUiPreferences.isDark(visualTheme, resources.configuration.uiMode)
        setTheme(if (darkTheme) org.sih26168.idrlogger.R.style.AppThemeDark else org.sih26168.idrlogger.R.style.AppThemeLight)
        super.onCreate(savedInstanceState)
        savedInstanceState?.let {
            currentPage = runCatching { Page.valueOf(it.getString("page") ?: "LIVE") }.getOrDefault(Page.LIVE)
            demoMode = runCatching { DemoMode.valueOf(it.getString("demo_mode") ?: "QUICK_SYNTHETIC") }.getOrDefault(DemoMode.QUICK_SYNTHETIC)
            selectedPreset = runCatching { FieldTestPreset.valueOf(it.getString("preset") ?: "MEDIUM") }.getOrDefault(FieldTestPreset.MEDIUM)
            selectedMount = runCatching { MountProfile.valueOf(it.getString("mount") ?: "DASHBOARD") }.getOrDefault(MountProfile.DASHBOARD)
        }
        window.statusBarColor = BACKGROUND
        window.navigationBarColor = BACKGROUND
        window.decorView.systemUiVisibility = if (darkTheme) {
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        } else {
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
        demoController = DemoController { snapshot, phase, paused ->
            runOnUiThread {
                latestDemo = snapshot; demoPhase = phase
                demoStartButton.text = if (paused) "RESUME" else "RUNNING"
                if (currentPage == Page.DEMO) updateDemo(snapshot)
            }
        }
        setContentView(buildUi(savedInstanceState))
        productSettingsRepository.load { loaded -> runOnUiThread {
            productSettings = loaded
            if (::liveTrajectory.isInitialized) {
                liveTrajectory.setPresentationOptions(loaded.showTrail, loaded.showUncertainty)
                liveTrajectory.selectRendererPreference(loaded.renderer)
            }
            updateSettings()
        } }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("page", currentPage.name)
        outState.putString("demo_mode", demoMode.name)
        outState.putString("preset", selectedPreset.name)
        outState.putString("mount", selectedMount.name)
        if (!themeChangePending) {
            val mapState = Bundle()
            if (runCatching { liveTrajectory.onSaveInstanceState(mapState) }.isSuccess) outState.putBundle("google_map", mapState)
            val navigationMapState = Bundle()
            if (runCatching { turnByTurnNavigation.onSaveInstanceState(navigationMapState) }.isSuccess) outState.putBundle("navigation_map", navigationMapState)
        }
        super.onSaveInstanceState(outState)
    }

    override fun onStart() {
        super.onStart(); liveTrajectory.onStart(); turnByTurnNavigation.onStart(); bindService(Intent(this, SensorLoggingService::class.java), connection, Context.BIND_AUTO_CREATE)
        uiHandler.post(refresh); uiHandler.post(mapRefresh)
    }

    override fun onResume() { super.onResume(); liveTrajectory.onResume(); turnByTurnNavigation.onResume() }

    override fun onPause() { turnByTurnNavigation.onPause(); liveTrajectory.onPause(); super.onPause() }

    override fun onStop() {
        demoController.pause(); publicReplayRunning = false; uiHandler.removeCallbacks(publicReplayTick)
        turnByTurnNavigation.onStop(); liveTrajectory.onStop(); uiHandler.removeCallbacks(refresh); uiHandler.removeCallbacks(mapRefresh)
        if (bound) unbindService(connection); bound = false; service = null; super.onStop()
    }

    override fun onDestroy() { demoController.close(); turnByTurnNavigation.onDestroy(); liveTrajectory.onDestroy(); super.onDestroy() }

    override fun onLowMemory() { super.onLowMemory(); liveTrajectory.onLowMemory(); turnByTurnNavigation.onLowMemory() }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_PERMISSIONS && pendingStart) {
            pendingStart = false
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) startRecordingService()
            else Toast.makeText(this, "Precise location is required for live GNSS initialization", Toast.LENGTH_LONG).show()
        }
    }

    @Deprecated("Native activity result retained to avoid an AndroidX dependency")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_EXPORT || resultCode != RESULT_OK) return
        val destination = data?.data ?: return; val source = exportSource ?: return
        try {
            contentResolver.openOutputStream(destination)?.use { output -> ZipOutputStream(output).use { zip -> zipDirectory(source, zip) } }
                ?: error("Cannot open export destination")
            Toast.makeText(this, "Session exported locally", Toast.LENGTH_LONG).show()
        } catch (error: Exception) {
            Toast.makeText(this, "Export failed: ${error.message}", Toast.LENGTH_LONG).show()
        } finally { exportSource = null }
    }

    private fun buildUi(savedInstanceState: Bundle?): View {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(BACKGROUND) }
        root.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft + dp(8), insets.systemWindowInsetTop + dp(4), insets.systemWindowInsetRight + dp(8), insets.systemWindowInsetBottom + dp(4)); insets
        }
        root.addView(buildHeader())
        val container = FrameLayout(this)
        liveScreen = buildLiveScreen(savedInstanceState?.getBundle("google_map"))
        turnByTurnNavigation = TurnByTurnNavigationView(
            this,
            savedInstanceState?.getBundle("navigation_map"),
            snapshotProvider = { service?.navigationSnapshot() ?: NavigationSnapshot() },
            onStartNavGhost = { if (service?.status()?.recording != true) requestStart() },
        )
        navigationScreen = turnByTurnNavigation
        productExperience = ProductExperience(this@MainActivity, darkTheme,
            snapshot = { service?.navigationSnapshot() ?: NavigationSnapshot() }, loggerStatus = { service?.status() },
            rendererLabel = { liveTrajectory.rendererSelectorLabel() }, onToggleNavigation = { if (service?.status()?.recording == true) stopRecordingService() else requestStart() },
            onOpenMap = { showPage(Page.LIVE) }, onOpenDemo = { showPage(Page.DEMO) }, onOpenEngineering = { showPage(Page.DIAGNOSTICS) },
            onExportDirectory = { beginExport(it) })
        dashboardScreen = productExperience.dashboardView; nearbyScreen = productExperience.nearbyView
        historyScreen = productExperience.historyView; insightsScreen = productExperience.insightsView
        demoScreen = buildDemoScreen(); diagnosticsScreen = buildDiagnosticsScreen(); settingsScreen = buildSettingsScreen()
        listOf(liveScreen, navigationScreen, dashboardScreen, nearbyScreen, historyScreen, insightsScreen, demoScreen, diagnosticsScreen, settingsScreen).forEach(container::addView)
        root.addView(container, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(buildTabs(), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(54)).apply { topMargin = dp(4) })
        showPage(currentPage); root.requestApplyInsets(); return root
    }

    private fun buildHeader(): View = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        addView(ImageView(this@MainActivity).apply { setImageResource(org.sih26168.idrlogger.R.drawable.ic_navghost_mark); contentDescription = "NavGhost" }, LinearLayout.LayoutParams(dp(36), dp(36)).apply { marginEnd = dp(8) })
        val titles = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        titles.addView(label("NAVGHOST", 20f, TEXT_PRIMARY, true).apply { letterSpacing = 0.04f })
        contextLabel = label("NAVIGATION BEYOND GNSS", 10f, ACCENT, true).apply { letterSpacing = 0.12f }
        titles.addView(contextLabel)
        recordingLabel = label("IDLE • LOCAL", 10f, TEXT_MUTED, true)
        recordingLabel.visibility = View.GONE // State is visible in the live HUD; diagnostics retain session details.
        titles.addView(recordingLabel)
        addView(titles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        stateChip = label("WAITING", 10f, TEXT_PRIMARY, true).apply { maxLines = 2; maxWidth = dp(125); gravity = Gravity.CENTER; setPadding(dp(8), dp(6), dp(8), dp(6)); background = rounded(SURFACE_HIGH, 20f) }
        addView(stateChip)
        addView(ghostButton("⚙") { showPage(Page.SETTINGS) }, LinearLayout.LayoutParams(dp(42), dp(42)).apply { marginStart = dp(3) })
    }

    private fun buildTabs(): View = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; background = rounded(SURFACE, 22f, BORDER); setPadding(dp(5), dp(4), dp(5), dp(4))
        listOf(Page.LIVE to "◇\n3D", Page.NAVIGATION to "➤\nGO", Page.DASHBOARD to "▦\nHOME", Page.NEARBY to "⌖\nNEARBY", Page.HISTORY to "◷\nTRIPS", Page.INSIGHTS to "⌁\nINSIGHTS").forEach { (page, title) ->
            val item = label(title, 10f, TEXT_MUTED, true).apply {
                gravity = Gravity.CENTER; letterSpacing = 0.06f; contentDescription = title.replace('\n', ' '); setOnClickListener { showPage(page) }
            }
            navItems[page] = item; addView(item, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { setMargins(dp(3), 0, dp(3), 0) })
        }
    }

    private fun buildLiveScreen(mapState: Bundle?): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; setPadding(0, dp(8), 0, 0)
        val mapFrame = FrameLayout(this@MainActivity).apply { background = rounded(SURFACE, 20f, BORDER); clipToOutline = true }
        liveTrajectory = NavGhostMapSurface(
            this@MainActivity,
            mapState,
            onDestinationSelected = { latitude, longitude ->
                turnByTurnNavigation.navigateToDroppedPin(latitude, longitude)
                showPage(Page.NAVIGATION)
            },
        ) { status -> mapPresentation = status; if (currentPage == Page.DIAGNOSTICS) updateDiagnostics() }
        mapFrame.addView(liveTrajectory, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        val statusHud = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(10), dp(12), dp(10))
            background = rounded(Color.argb(235, 8, 19, 30), 18f, BORDER)
        }
        modeHero = label("WAITING FOR GNSS", 16f, ACCENT, true)
        satelliteHud = label("SATELLITES  —", 12f, OVERLAY_SECONDARY)
        liveSecondary = label("ML ASSIST WARMING", 11f, OVERLAY_MUTED)
        statusHud.addView(modeHero); statusHud.addView(satelliteHud, margins(top = 5)); statusHud.addView(liveSecondary, margins(top = 3))
        mapFrame.addView(statusHud, FrameLayout.LayoutParams(dp(184), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.END).apply { setMargins(0, dp(10), dp(10), 0) })
        mapContextHud = label("3D HYBRID", 10f, OVERLAY_SECONDARY, true).apply {
            setPadding(dp(8), dp(6), dp(8), dp(6)); background = rounded(Color.argb(218, 8, 19, 30), 10f)
        }
        mapFrame.addView(mapContextHud, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.START).apply { setMargins(dp(10), dp(10), 0, 0) })
        val mapControls = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        mapOrientationButton = mapButton("CHASE") { liveTrajectory.toggleOrientation() }
        mapTypeButton = mapButton("3D") { mapTypeButton.text = liveTrajectory.cycleMapLayer() }
        recenterButton = mapButton("RECENTER") { liveTrajectory.recenter() }
        val directionsButton = mapButton("DIRECTIONS") { showPage(Page.NAVIGATION) }
        listOf(mapTypeButton, mapOrientationButton, recenterButton, directionsButton).forEach {
            mapControls.addView(it, LinearLayout.LayoutParams(dp(78), dp(46)).apply { topMargin = dp(5) })
        }
        mapFrame.addView(mapControls, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL or Gravity.END).apply { marginEnd = dp(10) })
        val bottomHud = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(6), dp(12), dp(6))
            background = rounded(Color.argb(235, 8, 19, 30), 18f, BORDER)
        }
        val metrics = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        speedHero = label("—", 34f, OVERLAY_PRIMARY, true)
        metrics.addView(speedHero)
        metrics.addView(label(" km/h", 12f, OVERLAY_MUTED), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        uncertaintyHero = label("—\nUNCERTAINTY", 14f, OVERLAY_SECONDARY, true).apply { gravity = Gravity.END }
        metrics.addView(uncertaintyHero)
        drTimer = label("DR 00:00", 12f, WARNING, true).apply { setPadding(dp(12), 0, 0, 0) }
        metrics.addView(drTimer)
        bottomHud.addView(metrics)
        telemetryIndicator = label("COMMAND CENTER OFF", 10f, OVERLAY_MUTED).apply { maxLines = 1 }
        bottomHud.addView(telemetryIndicator)
        mapFrame.addView(bottomHud, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM).apply { setMargins(dp(10), 0, dp(10), dp(8)) })
        calibrationCard = LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8))
            background = rounded(Color.argb(224, 8, 19, 30), 12f, BORDER)
            calibrationTitle = label("ALIGNING VEHICLE", 10f, WARNING, true).apply { maxLines = 1 }
            calibrationBody = label("Drive straight briefly", 10f, OVERLAY_SECONDARY).apply { maxLines = 1 }
            calibrationProgress = ProgressBar(this@MainActivity, null, android.R.attr.progressBarStyleHorizontal).apply {
                max = 100
                progressTintList = ColorStateList.valueOf(WARNING)
            }
            addView(calibrationTitle)
            addView(calibrationBody, margins(top = 2))
            addView(calibrationProgress, margins(top = 5, height = 3))
        }
        // Keep alignment guidance available without masking the central 3D scene.  The compact
        // banner sits below the provider badge and clear of the right-side map controls.
        mapFrame.addView(calibrationCard, FrameLayout.LayoutParams(dp(190), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.START).apply {
            setMargins(dp(10), dp(98), 0, 0)
        })
        fieldPanel = buildFieldTestCard().apply { visibility = View.GONE }
        mapFrame.addView(fieldPanel, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM).apply { setMargins(dp(12), 0, dp(12), dp(12)) })
        addView(mapFrame, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f).apply { bottomMargin = dp(8) })
        liveMessage = label("Ready for a trusted GNSS fix", 11f, TEXT_SECONDARY).apply { gravity = Gravity.CENTER; maxLines = 2 }
        addView(liveMessage, margins(bottom = 2))
        val actions = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL; isBaselineAligned = false }
        livePrimaryButton = actionButton("START NAVIGATION") { if (service?.status()?.recording == true) stopRecordingService() else requestStart() }
        actions.addView(livePrimaryButton, LinearLayout.LayoutParams(0, dp(52), 1.25f).apply { marginEnd = dp(4) })
        blackoutButton = compactButton("TEST TUNNEL") {
            val result = service?.setSimulatedBlackout(!(service?.status()?.simulatedBlackout ?: false))
            if (result?.allowed == false) {
                val message = result.message
                liveMessage.text = message
                Toast.makeText(this@MainActivity, message, Toast.LENGTH_LONG).show()
            } else {
                meaningfulHaptic(HapticFeedbackConstants.CONFIRM)
            }
        }
        actions.addView(blackoutButton, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginStart = dp(4); marginEnd = dp(4) })
        actions.addView(compactButton("FIELD TEST") { fieldPanel.visibility = if (fieldPanel.visibility == View.VISIBLE) View.GONE else View.VISIBLE }, LinearLayout.LayoutParams(0, dp(52), 0.8f).apply { marginStart = dp(4) })
        addView(actions, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)).apply { bottomMargin = dp(6) })
    }

    private fun buildFieldTestCard(): View = card().apply {
        addView(label("FIELD TEST • AUTOMATIC", 14f, ACCENT, true))
        addView(label("Configure while parked. Do not operate the phone while driving.", 13f, TEXT_SECONDARY), margins(top = 4))
        val selectors = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
        presetButton = compactButton("MEDIUM • 30 s") { cyclePreset() }
        mountButton = compactButton("MOUNT • DASHBOARD") { cycleMount() }
        selectors.addView(presetButton, weighted()); selectors.addView(mountButton, weighted())
        addView(selectors, margins(top = 8, height = 48))
        fieldStatus = label("Ready when recording, GNSS, and alignment are available.", 13f, TEXT_SECONDARY)
        addView(fieldStatus, margins(top = 7))
        fieldStartButton = actionButton("START AUTOMATIC FIELD TEST") {
            val running = service?.status()?.fieldTest?.phase !in setOf(null, FieldTestPhase.IDLE, FieldTestPhase.COMPLETE, FieldTestPhase.CANCELLED)
            if (running) service?.cancelFieldTest()
            else if (service?.startFieldTest(selectedPreset, selectedMount) != true) Toast.makeText(this@MainActivity, "Start live recording before the field test", Toast.LENGTH_LONG).show()
        }
        addView(fieldStartButton, margins(top = 8, height = 50))
    }

    private fun buildDemoScreen(): View {
        val content = verticalContent()
        content.addView(label("NavGhost Demo", 24f, TEXT_PRIMARY, true))
        demoBanner = label("NOT LIVE • DETERMINISTIC REPLAY", 12f, Color.WHITE, true).apply { gravity = Gravity.CENTER; letterSpacing = 0.08f; setPadding(dp(8), dp(8), dp(8), dp(8)); background = rounded(DEMO, 18f) }
        content.addView(demoBanner, margins(bottom = 8))
        demoPhaseLabel = label(demoPhase, 16f, TEXT_PRIMARY, true); content.addView(demoPhaseLabel)
        demoTimeline = label("● GNSS  ━  ○ TUNNEL  ━  ○ IDR  ━  ○ RECOVERY", 12f, TEXT_SECONDARY, true).apply { gravity = Gravity.CENTER; setPadding(dp(8), dp(10), dp(8), dp(10)); background = rounded(SURFACE, 14f, BORDER) }
        content.addView(demoTimeline, margins(top = 4, bottom = 8))
        demoTrajectory = TrajectoryView(this); content.addView(demoTrajectory, margins(height = 340, bottom = 10))
        demoMetrics = metricCard(); content.addView(demoMetrics, margins(bottom = 8))
        demoModeButton = compactButton("MODE • QUICK SYNTHETIC") { cycleDemoMode() }
        content.addView(demoModeButton, margins(height = 48, bottom = 6))
        comparisonButton = compactButton("COMPARE • INTELLIGENT IDR") { cycleDemoComparison() }
        content.addView(comparisonButton, margins(height = 48, bottom = 6))
        publicBenchmarkReplayButton = actionButton("START PUBLIC BENCHMARK") { startPublicBenchmarkReplay() }.apply { visibility = View.GONE }
        content.addView(publicBenchmarkReplayButton, margins(height = 50, bottom = 6))
        demoControls = GridLayout(this).apply { columnCount = 2; rowCount = 2 }
        demoStartButton = actionButton("START 30 s JUDGE DEMO") { if (demoMode == DemoMode.QUICK_SYNTHETIC) demoController.startOrResume() }
        demoControls.addView(demoStartButton, gridButton()); demoControls.addView(actionButton("PAUSE") { demoController.pause() }, gridButton())
        demoControls.addView(actionButton("RESET") { demoController.reset() }, gridButton()); demoControls.addView(actionButton("TRIGGER TUNNEL") { demoController.toggleManualBlackout() }, gridButton())
        content.addView(demoControls, margins(height = 110, bottom = 16))
        return ScrollView(this).apply { isFillViewport = true; addView(content) }
    }

    private fun buildDiagnosticsScreen(): View {
        val content = verticalContent()
        content.addView(label("SYSTEM HEALTH", 22f, TEXT_PRIMARY, true), margins(bottom = 4))
        healthOverview = label("SENSORS  •  GNSS  •  ENGINE  •  AI  •  MAP", 12f, ACCENT, true).apply { gravity = Gravity.CENTER; setPadding(dp(10), dp(11), dp(10), dp(11)); background = rounded(SURFACE_HIGH, 14f) }
        content.addView(healthOverview, margins(bottom = 10))
        listOf("SYSTEM", "SENSORS", "GNSS", "LOCALIZATION", "AI / OOD", "FIELD TEST", "SESSION", "PERFORMANCE", "MAP").forEach { title ->
            val value = label("Connecting…", 13f, TEXT_SECONDARY).apply { setTextIsSelectable(true); setLineSpacing(0f, 1.15f) }
            diagnostics[title] = value
            content.addView(card().apply { addView(label(title, 13f, ACCENT, true)); addView(value, margins(top = 6)) }, margins(bottom = 8))
        }
        content.addView(actionButton("EXPORT LAST LOCAL SESSION (.ZIP)") { beginExport() }, margins(height = 52, bottom = 18))
        content.addView(compactButton("ABOUT NAVGHOST") { showAbout() }, margins(height = 48, bottom = 18))
        return ScrollView(this).apply { addView(content) }
    }

    private fun buildSettingsScreen(): View {
        val content = verticalContent()
        content.addView(label("SETTINGS", 22f, TEXT_PRIMARY, true), margins(bottom = 3))
        content.addView(label("Presentation and optional connections only. Localization continues independently.", 12f, TEXT_SECONDARY), margins(bottom = 10))

        content.addView(card().apply {
            addView(label("APPEARANCE", 13f, ACCENT, true))
            themeButton = compactButton("THEME • ${visualTheme.name}") { cycleTheme() }
            addView(themeButton, margins(top = 7, height = 48))
            hapticsButton = compactButton("HAPTICS • ${if (hapticsEnabled) "ON" else "OFF"}") {
                hapticsEnabled = !hapticsEnabled
                uiPreferences.setHapticsEnabled(hapticsEnabled)
                productSettings = productSettings.copy(haptics = hapticsEnabled); productSettingsRepository.save(productSettings)
                hapticsButton.text = "HAPTICS • ${if (hapticsEnabled) "ON" else "OFF"}"
                meaningfulHaptic(HapticFeedbackConstants.CONFIRM)
            }
            addView(hapticsButton, margins(top = 5, height = 48))
        }, margins(bottom = 10))

        content.addView(card().apply {
            addView(label("MAP & CAMERA", 13f, ACCENT, true))
            addView(label("The map visualizes NavigationSnapshot output only; Google location and blue dot remain disabled.", 12f, TEXT_SECONDARY), margins(top = 5))
            settingsRendererButton = compactButton("RENDERER • ${liveTrajectory.rendererSelectorLabel()}") {
                liveTrajectory.cycleMapLayer()
                productSettings = productSettings.copy(renderer = liveTrajectory.rendererSelectorLabel()); productSettingsRepository.save(productSettings)
                updateSettings()
            }
            addView(settingsRendererButton, margins(top = 7, height = 48))
            settingsCameraButton = compactButton("CAMERA • ${if (liveTrajectory.isCinematic()) "NAVIGATION CHASE" else "NORTH-UP"}") {
                liveTrajectory.toggleOrientation()
                productSettings = productSettings.copy(headingUpCamera = liveTrajectory.isCinematic()); productSettingsRepository.save(productSettings)
                updateSettings()
            }
            addView(settingsCameraButton, margins(top = 5, height = 48))
            addView(label("FOLLOW CAMERA", 11f, ACCENT, true), margins(top = 8))
            addView(label("NavGhost follows when navigation starts. Drag the map to explore; follow stays paused until you tap Recenter.", 12f, TEXT_SECONDARY), margins(top = 3))
            settingsTrailButton = compactButton("SHOW TRAIL • ON") {
                productSettings = productSettings.copy(showTrail = !productSettings.showTrail)
                liveTrajectory.setPresentationOptions(productSettings.showTrail, productSettings.showUncertainty)
                productSettingsRepository.save(productSettings); updateSettings()
            }
            addView(settingsTrailButton, margins(top = 5, height = 48))
            settingsUncertaintyButton = compactButton("SHOW UNCERTAINTY • ON") {
                productSettings = productSettings.copy(showUncertainty = !productSettings.showUncertainty)
                liveTrajectory.setPresentationOptions(productSettings.showTrail, productSettings.showUncertainty)
                productSettingsRepository.save(productSettings); updateSettings()
            }
            addView(settingsUncertaintyButton, margins(top = 5, height = 48))
            settingsPerformanceButton = compactButton("PERFORMANCE MODE • OFF") {
                productSettings = productSettings.copy(performanceMode = !productSettings.performanceMode)
                productSettingsRepository.save(productSettings); updateSettings()
            }
            addView(settingsPerformanceButton, margins(top = 5, height = 48))
        }, margins(bottom = 10))

        content.addView(buildTelemetryCard(), margins(bottom = 10))
        content.addView(card().apply {
            addView(label("STORAGE", 13f, ACCENT, true))
            storageLabel = label("Calculating NavGhost-owned storage…", 13f, TEXT_SECONDARY)
            addView(storageLabel, margins(top = 6))
            addView(compactButton("CLEAR TEMPORARY CACHE") {
                val cleared = AppStorageAudit.clearTemporaryCache(this@MainActivity)
                Toast.makeText(this@MainActivity, "Cleared ${Formatter.formatShortFileSize(this@MainActivity, cleared)} of NavGhost temporary cache", Toast.LENGTH_LONG).show()
                updateSettings()
            }, margins(top = 7, height = 48))
            addView(label("Recorded field-test sessions are never removed here. Google Maps and Google Play Services caches are not managed by NavGhost.", 12f, TEXT_MUTED), margins(top = 6))
        }, margins(bottom = 10))
        content.addView(actionButton("ABOUT NAVGHOST") { showAbout() }, margins(height = 50, bottom = 18))
        return ScrollView(this).apply { isFillViewport = true; addView(content) }
    }

    private fun updateSettings() {
        if (!::settingsRendererButton.isInitialized) return
        themeButton.text = "THEME • ${visualTheme.name}"
        hapticsButton.text = "HAPTICS • ${if (hapticsEnabled) "ON" else "OFF"}"
        settingsRendererButton.text = "RENDERER • ${liveTrajectory.rendererSelectorLabel()}"
        settingsCameraButton.text = "CAMERA • ${if (liveTrajectory.isCinematic()) "NAVIGATION CHASE" else "NORTH-UP"}"
        settingsTrailButton.text = "SHOW TRAIL • ${if (productSettings.showTrail) "ON" else "OFF"}"
        settingsUncertaintyButton.text = "SHOW UNCERTAINTY • ${if (productSettings.showUncertainty) "ON" else "OFF"}"
        settingsPerformanceButton.text = "PERFORMANCE MODE • ${if (productSettings.performanceMode) "ON" else "OFF"}"
        val storage = AppStorageAudit.inspect(this)
        storageLabel.text = "Recordings  ${Formatter.formatShortFileSize(this, storage.recordingsBytes)}\nTemporary cache  ${Formatter.formatShortFileSize(this, storage.temporaryBytes)}"
    }

    private fun cycleTheme() {
        val values = VisualTheme.entries
        visualTheme = values[(values.indexOf(visualTheme) + 1) % values.size]
        uiPreferences.setTheme(visualTheme)
        productSettings = productSettings.copy(theme = visualTheme.name); productSettingsRepository.save(productSettings)
        themeChangePending = true
        recreate()
    }

    private fun buildTelemetryCard(): View = card().apply {
        val saved = TelemetrySettings(this@MainActivity).load()
        telemetryRateHz = saved.rateHz
        addView(label("COMMAND CENTER • OPTIONAL", 14f, ACCENT, true))
        addView(label("Share engine estimates with your trusted laptop. Navigation stays on this phone. No raw IMU or hidden GNSS is sent.", 13f, TEXT_SECONDARY), margins(top = 6))
        telemetryEnabled = Switch(this@MainActivity).apply {
            text = "Enable telemetry"; textSize = 15f; setTextColor(TEXT_PRIMARY); isChecked = saved.enabled
            contentDescription = "Enable optional Command Center telemetry"
        }
        addView(telemetryEnabled, margins(top = 8, height = 48))
        telemetryEndpoint = EditText(this@MainActivity).apply {
            setText(saved.endpoint); hint = "ws://<LAPTOP_IPV4>:8000/ws/telemetry"
            setTextColor(TEXT_PRIMARY); setHintTextColor(TEXT_MUTED); textSize = 14f
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine = true
            contentDescription = "Command Center WebSocket server address"
        }
        addView(telemetryEndpoint, margins(height = 52))
        telemetryRateButton = compactButton("RATE • $telemetryRateHz Hz") {
            val choices = listOf(1, 2, 5, 10)
            telemetryRateHz = choices[(choices.indexOf(telemetryRateHz) + 1) % choices.size]
            telemetryRateButton.text = "RATE • $telemetryRateHz Hz"
        }
        addView(telemetryRateButton, margins(top = 6, height = 48))
        val controls = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
        controls.addView(actionButton("APPLY & CONNECT") {
            productSettings = productSettings.copy(telemetryEnabled = telemetryEnabled.isChecked)
            productSettingsRepository.save(productSettings)
            val currentService = service
            val error = if (currentService == null) "Navigation service is connecting; try again" else currentService.configureTelemetry(
                TelemetryConfig(telemetryEnabled.isChecked, telemetryEndpoint.text.toString(), telemetryRateHz))
            if (error != null) Toast.makeText(this@MainActivity, error, Toast.LENGTH_LONG).show()
            updateTelemetryStatus()
        }, weighted())
        controls.addView(compactButton("DISCONNECT") { service?.disconnectTelemetry(); updateTelemetryStatus() }, weighted())
        addView(controls, margins(top = 6, height = 52))
        addView(label("5 Hz default • 10 Hz maximum. Cleartext ws:// requires a trusted LAN host in this APK; use wss:// on untrusted networks. Configure only while parked.", 12f, TEXT_MUTED), margins(top = 8))
        telemetryDetails = label("Telemetry disabled by default", 13f, TEXT_SECONDARY).apply { setTextIsSelectable(true) }
        addView(telemetryDetails, margins(top = 8))
    }

    private fun updateTelemetryStatus() {
        val status = service?.telemetryStatus()
        val state = status?.state ?: TelemetryConnectionState.DISABLED
        if (::telemetryIndicator.isInitialized) {
            telemetryIndicator.text = when (state) {
                TelemetryConnectionState.CONNECTED -> "● COMMAND CENTER CONNECTED"
                TelemetryConnectionState.DISABLED -> "COMMAND CENTER OFF"
                TelemetryConnectionState.CONNECTING -> "COMMAND CENTER CONNECTING"
                else -> "COMMAND CENTER OFFLINE"
            }
            telemetryIndicator.setTextColor(if (state == TelemetryConnectionState.CONNECTED) ACCENT else OVERLAY_MUTED)
        }
        if (::telemetryDetails.isInitialized && status != null) {
            val age = status.lastSendTimestampNs?.let { String.format(Locale.US, "%.1f s", (System.nanoTime() - it).coerceAtLeast(0L) / 1e9) } ?: "N/A"
            telemetryDetails.text = "State ${state.name}\nLast sent $age ago • Rate ${status.rateHz} Hz\nSent ${status.sentMessages} • Coalesced ${status.coalescedMessages} • Dropped ${status.droppedMessages}\nRetries ${status.reconnectAttempts} • Errors ${status.errorCount}\nQueue ${status.queuedMessages}/1 • Socket ${status.queuedBytes} bytes\n${status.lastError ?: "One-way observer; navigation is independent"}"
        }
    }

    private fun showPage(page: Page) {
        currentPage = page
        val target = when (page) {
            Page.LIVE -> liveScreen; Page.NAVIGATION -> navigationScreen; Page.DASHBOARD -> dashboardScreen; Page.NEARBY -> nearbyScreen
            Page.HISTORY -> historyScreen; Page.INSIGHTS -> insightsScreen; Page.DEMO -> demoScreen
            Page.DIAGNOSTICS -> diagnosticsScreen; Page.SETTINGS -> settingsScreen
        }
        listOf(liveScreen, navigationScreen, dashboardScreen, nearbyScreen, historyScreen, insightsScreen, demoScreen, diagnosticsScreen, settingsScreen).forEach { it.visibility = if (it === target) View.VISIBLE else View.GONE }
        target.animate().cancel()
        target.alpha = 0.72f
        target.translationY = dp(10).toFloat()
        target.scaleX = 0.985f
        target.scaleY = 0.985f
        target.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
            .setDuration(220L).setInterpolator(DecelerateInterpolator(1.7f)).start()
        contextLabel.text = when (page) {
            Page.LIVE -> "NAVIGATION BEYOND GNSS"; Page.NAVIGATION -> "TURN-BY-TURN NAVIGATION"; Page.DASHBOARD -> "JOURNEY DASHBOARD"; Page.NEARBY -> "NEARBY PLACES"
            Page.HISTORY -> "TRIP HISTORY"; Page.INSIGHTS -> "LOCAL INSIGHTS"; Page.DEMO -> "DEMO REPLAY • NOT LIVE"
            Page.DIAGNOSTICS -> "SYSTEM DIAGNOSTICS"; Page.SETTINGS -> "PRODUCT SETTINGS"
        }
        navItems.forEach { (itemPage, item) ->
            val selected = itemPage == page; item.setTextColor(if (selected) ACCENT else TEXT_MUTED); item.background = if (selected) rounded(SURFACE_HIGH, 18f) else null
        }
        updateUi()
        if (page == Page.LIVE) updateLiveMap()
        if (page == Page.NAVIGATION) updateNavigationMap()
        if (page == Page.HISTORY || page == Page.INSIGHTS) productExperience.refreshHistory()
        if (page == Page.NEARBY) productExperience.updateNearbyAnchor()
    }

    private fun updateUi() {
        updateTelemetryStatus()
        if (::liveTrajectory.isInitialized) service?.setTelemetryMapMode(liveTrajectory.isGoogleMapActive())
        if (::liveTrajectory.isInitialized) service?.setProductRendererLabel(liveTrajectory.rendererSelectorLabel())
        when (currentPage) {
            Page.LIVE -> updateLive(); Page.NAVIGATION -> updateNavigationMap(); Page.DASHBOARD -> productExperience.updateDashboard(); Page.NEARBY -> productExperience.updateNearbyAnchor()
            Page.HISTORY -> Unit; Page.INSIGHTS -> Unit; Page.DEMO -> updateDemo(latestDemo)
            Page.DIAGNOSTICS -> updateDiagnostics(); Page.SETTINGS -> updateSettings()
        }
    }

    private fun updateLive() {
        renderLive(service?.navigationSnapshot() ?: NavigationSnapshot(), service?.status())
    }

    private fun updateLiveMap() {
        if (currentPage != Page.LIVE || !::liveTrajectory.isInitialized) return
        val snapshot = service?.navigationSnapshot() ?: return
        liveTrajectory.show(snapshot, ViewportMode.FOLLOW_CURRENT)
        mapPresentation = liveTrajectory.status()
    }

    private fun updateNavigationMap() {
        if (currentPage != Page.NAVIGATION || !::turnByTurnNavigation.isInitialized) return
        turnByTurnNavigation.update(service?.navigationSnapshot() ?: NavigationSnapshot())
    }

    /** Rendering boundary: snapshots are immutable, and map/HUD work never invokes the estimator. */
    private fun renderLive(snapshot: NavigationSnapshot, status: org.sih26168.idrlogger.model.LoggerStatus?) {
        val nav = snapshot.state
        mapPresentation = liveTrajectory.status()
        liveMessage.text = nav.message
        mapContextHud.text = when (liveTrajectory.layerLabel()) {
            "GOOGLE 3D" -> "3D HYBRID"
            "MAPLIBRE 3D" -> "MAPLIBRE 3D"
            "GOOGLE LEGACY" -> "GOOGLE MAP"
            else -> "LOCAL ENU"
        }
        val positionHighlyUncertain = UiSemantics.positionHighlyUncertain(nav)
        val positionUnavailable = UiSemantics.positionUnavailable(nav)
        speedHero.text = if (nav.sequenceId >= 0 && nav.latitudeDeg != null && !positionHighlyUncertain) {
            String.format(Locale.US, "%.0f", nav.speedMps * 3.6)
        } else "—"
        modeHero.text = when {
            positionUnavailable -> "POSITION UNAVAILABLE"
            positionHighlyUncertain -> "POSITION HIGHLY UNCERTAIN"
            else -> when (nav.localizationMode) {
            LocalizationMode.WAITING_FOR_GNSS -> "WAITING FOR GNSS"
            LocalizationMode.GNSS_RECOVERING -> "RECOVERING"
            LocalizationMode.IDR_ACTIVE -> if (nav.motionState.name == "LIKELY_STATIONARY") "IDR ACTIVE · STATIONARY" else "IDR ACTIVE"
            else -> UiSemantics.localizationLabel(nav.localizationMode)
            }
        }
        val stateColor = org.sih26168.idrlogger.map.MapStateStyle.color(nav.localizationMode)
        modeHero.setTextColor(stateColor)
        satelliteHud.text = "SATELLITES ${status?.gnssDiagnostics?.satellitesVisible ?: "—"} / ${status?.gnssDiagnostics?.satellitesUsedInFix ?: "—"} used"
        uncertaintyHero.text = "${nav.horizontalUncertaintyM?.takeIf { it.isFinite() }?.let { String.format(Locale.US, "± %.1f m", it) } ?: "—"}\nUNCERTAINTY"
        uncertaintyHero.setTextColor(stateColor)
        liveSecondary.text = UiSemantics.aiLabel(nav.mlState)
        val drRelevant = nav.localizationMode in setOf(LocalizationMode.IDR_ACTIVE, LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING)
        drTimer.visibility = if (drRelevant) View.VISIBLE else View.GONE
        val drSeconds = nav.drDurationSeconds.toInt().coerceAtLeast(0)
        drTimer.text = String.format(Locale.US, "DR\n%02d:%02d", drSeconds / 60, drSeconds % 60)
        drTimer.setTextColor(stateColor)
        calibrationCard.visibility = if (nav.alignmentState == AlignmentState.READY || nav.latitudeDeg == null) View.GONE else View.VISIBLE
        calibrationTitle.text = if (nav.localizationMode == LocalizationMode.CALIBRATION_REQUIRED) "ALIGNMENT REQUIRED • POSITION HELD" else "ALIGNING VEHICLE"
        calibrationBody.text = when {
            nav.latitudeDeg == null -> "Waiting for trusted GNSS"
            nav.motionState.name == "LIKELY_STATIONARY" -> "Drive straight briefly"
            else -> "Keep a steady straight course"
        }
        calibrationProgress.progress = (nav.alignmentProgress.coerceIn(0.0, 1.0) * 100).toInt()
        val blackoutActive = status?.simulatedBlackout == true
        blackoutButton.text = if (blackoutActive) "END BLACKOUT" else "TEST TUNNEL"
        blackoutButton.setTextColor(if (blackoutActive) WARNING else TEXT_SECONDARY)
        blackoutButton.contentDescription = if (blackoutActive) "Simulated GNSS blackout active. End simulation" else "Start simulated GNSS blackout test"
        if (blackoutActive) liveMessage.text = if (status?.gnssDiagnostics?.blackoutMasksFreshFix == true) {
            "SIMULATED GNSS BLACKOUT • fresh physical GNSS fix masked for test"
        } else {
            "SIMULATED GNSS BLACKOUT • no fresh physical fix available to mask"
        } else if (status?.message?.startsWith("TUNNEL TEST UNAVAILABLE") == true) {
            liveMessage.text = status.message
        } else if (positionHighlyUncertain) {
            liveMessage.text = nav.message
        }
        livePrimaryButton.text = if (status?.recording == true) "STOP NAVIGATION" else "START NAVIGATION"
        recordingLabel.text = if (status?.recording == true) "● LIVE • LOCAL" else "IDLE • LOCAL"
        recordingLabel.setTextColor(if (status?.recording == true) ACCENT else TEXT_MUTED)
        mapOrientationButton.isEnabled = liveTrajectory.isGoogleMapActive()
        mapOrientationButton.text = if (liveTrajectory.layerLabel().contains("3D")) "3D CHASE" else if (liveTrajectory.isCinematic()) "CINEMATIC" else "NORTH ↑"
        mapTypeButton.text = if (liveTrajectory.layerLabel() == "GOOGLE 3D") "3D" else liveTrajectory.layerLabel().replace("GOOGLE ", "")
        recenterButton.setTextColor(if (liveTrajectory.isFollowing()) OVERLAY_SECONDARY else ACCENT)
        recenterButton.contentDescription = if (liveTrajectory.isFollowing()) "Recenter cinematic camera" else "Follow paused. Recenter cinematic camera"
        mapTypeButton.isEnabled = liveTrajectory.supportsMapLayers()
        mapOrientationButton.alpha = if (mapOrientationButton.isEnabled) 1f else 0.45f
        mapTypeButton.alpha = if (mapTypeButton.isEnabled) 1f else 0.45f
        if (status?.recording == true) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        updateFieldStatus(status)
        updateStateChip(nav.localizationMode, false)
        maybeHapticTransition(nav.localizationMode)
    }

    private fun updateFieldStatus(status: org.sih26168.idrlogger.model.LoggerStatus?) {
        val field = status?.fieldTest
        val running = field?.phase !in setOf(null, FieldTestPhase.IDLE, FieldTestPhase.COMPLETE, FieldTestPhase.CANCELLED)
        presetButton.text = "${selectedPreset.name} • ${selectedPreset.blackoutDurationSeconds} s"; mountButton.text = "MOUNT • ${selectedMount.name.replace('_', ' ')}"
        presetButton.isEnabled = !running; mountButton.isEnabled = !running
        fieldStartButton.text = if (running) "CANCEL FIELD TEST" else "START AUTOMATIC FIELD TEST"
        fieldStatus.text = if (field == null || field.phase == FieldTestPhase.IDLE) "Ready when recording, GNSS, and alignment are available."
        else "${field.phase.name.replace('_', ' ')} • ${field.phaseRemainingSeconds?.let { String.format(Locale.US, "%.0f s remaining", it) } ?: "waiting for safe prerequisites"}"
    }

    private fun updateDemo(snapshot: NavigationSnapshot) {
        if (demoMode == DemoMode.PUBLIC_BENCHMARK) { updatePublicBenchmark(); return }
        val (points, name) = demoComparisonTrack(snapshot)
        val secondary = if (demoComparison == DemoComparison.SHOW_ALL) syntheticRawTrack(snapshot.trajectory.size) else emptyList()
        demoTrajectory.show(snapshot, ViewportMode.AUTO_FIT, points, name, mapPresentation, secondary, if (secondary.isEmpty()) null else "SYNTHETIC RAW DR")
        demoBanner.text = "NOT LIVE • QUICK SYNTHETIC"
        contextLabel.text = "SYNTHETIC REPLAY • NOT LIVE"
        demoModeButton.text = "MODE • QUICK SYNTHETIC"
        demoPhaseLabel.text = demoNarrative(snapshot.state.localizationMode, demoPhase)
        demoTimeline.text = demoTimeline(snapshot.state.localizationMode)
        demoMetrics.text = "QUICK JUDGE DEMO • 27 s deterministic replay\n${shortMode(snapshot.state.localizationMode)}    ${UiSemantics.aiLabel(snapshot.state.mlState)}\nSPEED ${String.format(Locale.US, "%.1f km/h", snapshot.state.speedMps * 3.6)}    DR ${String.format(Locale.US, "%.1f s", snapshot.state.drDurationSeconds)}"
        demoStartButton.isEnabled = true
        demoControls.visibility = View.VISIBLE
        publicBenchmarkReplayButton.visibility = View.GONE
        updateStateChip(snapshot.state.localizationMode, true)
    }

    private fun updatePublicBenchmark() {
        val replay = PublicBenchmarkFixture.replay
        val visibleCount = if (publicReplayRunning) publicReplayIndex.coerceIn(1, replay.intelligentIdr.size) else replay.intelligentIdr.size
        val intelligentTrack = replay.intelligentIdr.take(visibleCount)
        val current = intelligentTrack.last()
        val snapshot = NavigationSnapshot(
            state = NavigationState(eastM = current.eastM, northM = current.northM, localizationMode = LocalizationMode.IDR_ACTIVE, horizontalUncertaintyM = 162.37),
            trajectory = intelligentTrack,
            isDemoReplay = true,
        )
        val comparison = when (demoComparison) {
            DemoComparison.INTELLIGENT_IDR -> Triple(emptyList<TrajectoryPoint>(), null, emptyList<TrajectoryPoint>())
            DemoComparison.RAW_DR -> Triple(replay.rawDr.take(visibleCount), "RAW DR", emptyList())
            DemoComparison.REFERENCE -> Triple(replay.reference.take(visibleCount), "VBOX EVALUATION REFERENCE", emptyList())
            DemoComparison.SHOW_ALL -> Triple(replay.reference.take(visibleCount), "VBOX REFERENCE", replay.rawDr.take(visibleCount))
        }
        demoTrajectory.show(snapshot, ViewportMode.AUTO_FIT, comparison.first, comparison.second, mapPresentation, comparison.third, if (comparison.third.isEmpty()) null else "RAW DR")
        demoBanner.text = "NOT LIVE • PUBLIC BENCHMARK"
        contextLabel.text = "PUBLIC BENCHMARK • NOT LIVE"
        demoModeButton.text = "MODE • PUBLIC BENCHMARK"
        val elapsed = ((visibleCount - 1) * replay.metrics.durationSeconds / (replay.intelligentIdr.size - 1)).coerceAtMost(replay.metrics.durationSeconds)
        demoPhaseLabel.text = String.format(Locale.US, "IO-VNBD • %s • %.0f / %.0f s STOP/GO", replay.metrics.scenarioId, elapsed, replay.metrics.durationSeconds)
        demoMetrics.text = String.format(Locale.US, "REFERENCE DISTANCE %.1f m\nINTELLIGENT %.2f m • %.2f%% DRIFT\nRAW DR %.2f m • EVALUATOR-ONLY COMPARISON", replay.metrics.referenceDistanceM, replay.metrics.intelligentFinalErrorM, replay.metrics.intelligentDriftPercent, replay.metrics.rawFinalErrorM)
        demoTimeline.text = "● GNSS  ━  ● 60 s BLACKOUT  ━  ● NAVGhost IDR  ━  ● EVALUATION"
        demoControls.visibility = View.GONE
        publicBenchmarkReplayButton.visibility = View.VISIBLE
        publicBenchmarkReplayButton.text = when {
            publicReplayRunning -> "RUNNING • ${elapsed.toInt()} / ${replay.metrics.durationSeconds.toInt()} s"
            publicReplayHasCompleted -> "REPLAY PUBLIC BENCHMARK"
            else -> "START PUBLIC BENCHMARK"
        }
        updateStateChip(LocalizationMode.IDR_ACTIVE, true)
    }

    private fun startPublicBenchmarkReplay() {
        uiHandler.removeCallbacks(publicReplayTick)
        publicReplayIndex = 1
        publicReplayRunning = true
        updatePublicBenchmark()
        uiHandler.postDelayed(publicReplayTick, PUBLIC_REPLAY_INTERVAL_MS)
    }

    private fun demoComparisonTrack(snapshot: NavigationSnapshot): Pair<List<TrajectoryPoint>, String?> {
        val count = snapshot.trajectory.size
        return when (demoComparison) {
            DemoComparison.INTELLIGENT_IDR -> emptyList<TrajectoryPoint>() to null
            DemoComparison.REFERENCE -> (0 until count).map { TrajectoryPoint(it * 0.8, 0.0, LocalizationMode.GNSS_ACTIVE) } to "SYNTHETIC REFERENCE"
            DemoComparison.RAW_DR -> (0 until count).map {
                val drift = if (it <= 60) 0.0 else 0.012 * minOf(it - 60, 100) * minOf(it - 60, 100)
                TrajectoryPoint(it * 0.8 + drift, drift * 0.3, LocalizationMode.IDR_ACTIVE)
            } to "SYNTHETIC RAW DR"
            DemoComparison.SHOW_ALL -> (0 until count).map { TrajectoryPoint(it * 0.8, 0.0, LocalizationMode.GNSS_ACTIVE) } to "SYNTHETIC REFERENCE"
        }
    }

    private fun syntheticRawTrack(count: Int): List<TrajectoryPoint> = (0 until count).map {
        val drift = if (it <= 60) 0.0 else 0.012 * minOf(it - 60, 100) * minOf(it - 60, 100)
        TrajectoryPoint(it * 0.8 + drift, drift * 0.3, LocalizationMode.IDR_ACTIVE)
    }

    private fun demoNarrative(mode: LocalizationMode, fallback: String): String = when (mode) {
        LocalizationMode.GNSS_ACTIVE -> if (fallback.contains("REACQUISITION")) "NAVIGATION RESTORED" else "NAVIGATION ACTIVE"
        LocalizationMode.IDR_ACTIVE -> "NavGhost IDR ACTIVE • POSITION ESTIMATE CONTINUES"
        LocalizationMode.GNSS_VERIFYING -> "GNSS DETECTED • VERIFYING SIGNAL"
        LocalizationMode.GNSS_RECOVERING -> "RECONCILING POSITION"
        LocalizationMode.GNSS_DEGRADED -> "ENTERING TUNNEL • GNSS SIGNAL LOST"
        else -> fallback
    }

    private fun demoTimeline(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.IDR_ACTIVE -> "● GNSS  ━  ● TUNNEL  ━  ● IDR ACTIVE  ━  ○ RECOVERY"
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> "● GNSS  ━  ● TUNNEL  ━  ● IDR  ━  ● RECOVERY"
        LocalizationMode.GNSS_ACTIVE -> "● GNSS  ━  ○ TUNNEL  ━  ○ IDR  ━  ○ RECOVERY"
        else -> "● READY  ━  ○ TUNNEL  ━  ○ IDR  ━  ○ RECOVERY"
    }

    private fun updateDiagnostics() {
        val state = service?.status(); val nav = service?.navigationSnapshot()?.state ?: NavigationState()
        if (state == null) { diagnostics.values.forEach { it.text = "Logger service connecting…" }; return }
        val a = state.availability; val r = state.rates; val d = state.gnssDiagnostics; val h = state.systemHealth
        healthOverview.text = "SENSORS ${if (a.accelerometer && a.gyroscope) "READY" else "CHECK"}   •   GNSS ${d.runtimeGnssAvailability}\nENGINE ${if (nav.sequenceId >= 0) "READY" else "WAITING"}   •   ${UiSemantics.aiLabel(nav.mlState)}   •   ${mapPresentation.primaryLabel}"
        diagnostics["SENSORS"]?.text = "Accelerometer ${a.accelerometer} • ${String.format(Locale.US, "%.1f Hz", r.accelerometerHz)}\nGyroscope ${a.gyroscope} • ${String.format(Locale.US, "%.1f Hz", r.gyroscopeHz)}\nMagnetometer ${a.magnetometer} • ${String.format(Locale.US, "%.1f Hz", r.magnetometerHz)}\nGravity ${a.gravity} • ${String.format(Locale.US, "%.1f Hz", r.gravityHz)}\nRotation vector ${a.rotationVector} • ${String.format(Locale.US, "%.1f Hz", r.rotationVectorHz)}"
        diagnostics["GNSS"]?.text = "Physical GNSS ${d.physicalFixState}\nRuntime GNSS ${d.runtimeGnssAvailability}\nReal fix acquired this session ${d.hasAcquiredRealFixThisSession}\nBlackout active ${state.simulatedBlackout}\nBlackout masking fresh fix ${d.blackoutMasksFreshFix}\nCallbacks ${d.physicalCallbackCount} • age ${d.latestPhysicalCallbackAgeSeconds?.let { String.format(Locale.US, "%.1f s", it) } ?: "N/A"}\nSatellites visible / used ${d.satellitesVisible ?: "N/A"} / ${d.satellitesUsedInFix ?: "N/A"}\nTTFF ${d.timeToFirstFixSeconds?.let { String.format(Locale.US, "%.1f s", it) } ?: "N/A"}"
        diagnostics["LOCALIZATION"]?.text = "Localization ${UiSemantics.localizationLabel(nav.localizationMode)}\nInternal ${nav.localizationMode}\nAlignment ${nav.alignmentState} • ${String.format(Locale.US, "%.0f%%", nav.alignmentProgress * 100)}\nMotion ${nav.motionState}\nConfidence ${nav.confidence}\nMarker source IdrEngine only"
        diagnostics["AI / OOD"]?.text = "User state ${UiSemantics.aiLabel(nav.mlState)}\nInternal state ${nav.mlState}\nFeature exceedance ${nav.mlOodExceedance?.let { String.format(Locale.US, "%.3f", it) } ?: "N/A"}\nResidual correction ${nav.mlResidualMps?.let { String.format(Locale.US, "%.3f m/s", it) } ?: "N/A"}"
        diagnostics["FIELD TEST"]?.text = "Phase ${state.fieldTest.phase}\nPreset ${state.fieldTest.preset ?: "N/A"}\nMount ${state.fieldTest.mountProfile}\nBlackout ${state.fieldTest.blackoutActive}\n${state.fieldTest.safetyMessage}"
        diagnostics["SESSION"]?.text = "Recording ${state.recording}\nElapsed ${String.format(Locale.US, "%.1f s", state.elapsedSeconds)}\nDirectory ${state.sessionDirectory ?: "none"}\nZIP export available\nRecordings app-private; optional engine-only LAN telemetry"
        val mapPerf = liveTrajectory.google3dPerformanceStats()
        val engineAgeMs = nav.monotonicTimestampNs.takeIf { it > 0L }
            ?.let { ((SystemClock.elapsedRealtimeNanos() - it).coerceAtLeast(0L)) / 1e6 }
        diagnostics["PERFORMANCE"]?.text = "Engine average ${String.format(Locale.US, "%.3f ms/sample", nav.engineAverageMs)} • P95 ${String.format(Locale.US, "%.3f ms/sample", nav.engineP95Ms)}\nENGINE AGE ${formatAgeMs(engineAgeMs)} • GNSS AGE ${statusAge(state.gnssAgeSeconds)}\nSNAPSHOT AGE ${formatAgeMs(mapPerf.offeredSnapshotAgeMs)} • RENDER AGE ${formatAgeMs(mapPerf.renderedSnapshotAgeMs)}\nCAMERA DELTA ${mapPerf.cameraToEstimatorDistanceM?.let { String.format(Locale.US, "%.1f m", it) } ?: "N/A"}\nESTIMATOR ${String.format(Locale.US, "%.1f Hz", r.normalizedHz)} • RENDER ${String.format(Locale.US, "%.1f Hz", mapPerf.renderedSnapshotHz)} • FOLLOW ${String.format(Locale.US, "%.1f Hz", mapPerf.cameraCommandHz)}\nFrozen GRU 4,257 parameters"
        if (::rendererSelectorButton.isInitialized) rendererSelectorButton.text = "RENDERER • ${liveTrajectory.rendererSelectorLabel()}"
        diagnostics["MAP"]?.text = "Provider ${mapPresentation.providerId}\nStatus ${mapPresentation.availability}\n${mapPresentation.detailLabel}\nRenderer ${liveTrajectory.layerLabel()} • selector ${liveTrajectory.rendererSelectorLabel()}\nAUTO order Google 3D → MapLibre 3D → Google legacy → Local ENU\nMode ${liveTrajectory.mapModeLabel()} • Follow ${liveTrajectory.isFollowing()}\nGoogle location/blue dot DISABLED\nMarker source NavGhost engine only"
        diagnostics["SYSTEM"]?.text = "NavGhost v${BuildConfig.VERSION_NAME}\nBattery ${h.batteryPercent?.let { String.format(Locale.US, "%.0f%%", it) } ?: "N/A"}\nBattery temperature ${h.batteryTemperatureC?.let { String.format(Locale.US, "%.1f °C", it) } ?: "N/A"}\nThermal state ${h.thermalStatus ?: "N/A"}\nForeground service ${h.foregroundServiceActive}\nLogger errors ${h.loggerErrorCount}\nLogger ${if (state.recording) "ACTIVE" else "IDLE"} • Engine ${if (nav.sequenceId >= 0) "ACTIVE" else "WAITING"} • UI ACTIVE"
        updateStateChip(nav.localizationMode, false)
    }

    private fun formatAgeMs(value: Double?): String = value?.takeIf { it.isFinite() }
        ?.let { String.format(Locale.US, "%.0f ms", it) } ?: "N/A"

    private fun statusAge(value: Double?): String = value?.takeIf { it.isFinite() }
        ?.let { String.format(Locale.US, "%.2f s", it) } ?: "N/A"

    private fun updateStateChip(mode: LocalizationMode, demo: Boolean) {
        stateChip.text = if (demo) "DEMO • ${shortChip(mode)}" else shortChip(mode); stateChip.background = rounded(chipColor(mode), 22f)
        stateChip.setTextColor(if (mode in setOf(LocalizationMode.WAITING_FOR_GNSS, LocalizationMode.CALIBRATING, LocalizationMode.GNSS_DEGRADED)) TEXT_PRIMARY else Color.WHITE)
    }

    private fun shortChip(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.WAITING_FOR_GNSS -> "WAITING"
        LocalizationMode.CALIBRATION_REQUIRED -> "CALIBRATION NEEDED"
        LocalizationMode.GNSS_VERIFYING -> "VERIFYING"
        LocalizationMode.GNSS_RECOVERING -> "RECOVERING"
        else -> UiSemantics.localizationLabel(mode)
    }

    private fun shortMode(mode: LocalizationMode): String = when (mode) {
        LocalizationMode.GNSS_ACTIVE -> "GNSS"; LocalizationMode.IDR_ACTIVE -> "IDR"
        LocalizationMode.GNSS_VERIFYING -> "VERIFYING"; LocalizationMode.GNSS_RECOVERING -> "RECOVERY"
        LocalizationMode.CALIBRATION_REQUIRED -> "HELD"; LocalizationMode.CALIBRATING -> "CALIBRATE"
        else -> mode.name.replace('_', ' ')
    }

    private fun chipColor(mode: LocalizationMode): Int = when (mode) {
        LocalizationMode.GNSS_ACTIVE -> HEALTHY; LocalizationMode.IDR_ACTIVE, LocalizationMode.CALIBRATION_REQUIRED -> WARNING
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> DEMO; LocalizationMode.ERROR -> CRITICAL; else -> SURFACE_HIGH
    }

    private fun cyclePreset() {
        val values = FieldTestPreset.entries; selectedPreset = values[(values.indexOf(selectedPreset) + 1) % values.size]; presetButton.text = "${selectedPreset.name} • ${selectedPreset.blackoutDurationSeconds} s"
    }
    private fun cycleMount() {
        val values = MountProfile.entries; selectedMount = values[(values.indexOf(selectedMount) + 1) % values.size]; mountButton.text = "MOUNT • ${selectedMount.name.replace('_', ' ')}"
    }
    private fun cycleDemoComparison() {
        val values = DemoComparison.entries; demoComparison = values[(values.indexOf(demoComparison) + 1) % values.size]
        comparisonButton.text = "COMPARE • ${demoComparison.name.replace('_', ' ')}"; updateDemo(latestDemo)
    }
    private fun cycleDemoMode() {
        demoController.pause()
        publicReplayRunning = false
        uiHandler.removeCallbacks(publicReplayTick)
        demoMode = if (demoMode == DemoMode.QUICK_SYNTHETIC) DemoMode.PUBLIC_BENCHMARK else DemoMode.QUICK_SYNTHETIC
        demoModeButton.text = if (demoMode == DemoMode.QUICK_SYNTHETIC) "MODE • QUICK SYNTHETIC" else "MODE • PUBLIC BENCHMARK"
        updateDemo(latestDemo)
    }

    private fun showAbout() {
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(8), dp(22), dp(4))
            addView(ImageView(this@MainActivity).apply {
                setImageResource(org.sih26168.idrlogger.R.drawable.ic_navghost_mark)
                contentDescription = "NavGhost mark"
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(82)))
            addView(label("NAVIGATION BEYOND GNSS", 12f, ACCENT, true).apply {
                gravity = Gravity.CENTER; letterSpacing = 0.12f
            }, margins(bottom = 12))
            addView(label("Smartphone-only intelligent dead reckoning that continues through GNSS loss.", 15f, TEXT_PRIMARY, true), margins(bottom = 12))
            addView(label("Built for Smart India Hackathon problem SIH26168\n\nAI-ML based Intelligent Dead Reckoning system for seamless navigation\n\nProblem-statement organization: ISRO / Department of Space\n\nIndependent hackathon project; not an official, endorsed, or certified ISRO application.", 13f, TEXT_SECONDARY), margins(bottom = 14))
            addView(label("GNSS + PHONE IMU → SIGNAL CONDITIONING → VEHICLE ALIGNMENT → SIX-STATE EKF → SAFETY-GATED ML RESIDUAL → UNCERTAINTY-AWARE RECOVERY", 12f, TEXT_MUTED, true), margins(bottom = 12))
            addView(label("The map is visualization only. Localization is produced by NavGhost; Google location and blue dot are disabled.", 12f, TEXT_SECONDARY), margins(bottom = 12))
            addView(label("FROZEN GRU • 4,257 PARAMETERS\nSHA-256 fa2169781f9e…0bb4ec\n~10 Hz ON-DEVICE • NO OBD-II • NO CUSTOM HARDWARE", 11f, TEXT_MUTED, true))
        }
        AlertDialog.Builder(this)
            .setTitle("NavGhost v${BuildConfig.VERSION_NAME}")
            .setView(ScrollView(this).apply { addView(body) })
            .setPositiveButton("DONE", null)
            .show()
    }

    private fun verticalContent() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(10), 0, 0) }
    private fun card() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(12), dp(14), dp(12)); background = rounded(SURFACE, 15f, BORDER) }
    private fun label(value: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply { text = value; textSize = size; setTextColor(color); if (bold) setTypeface(typeface, Typeface.BOLD) }
    private fun metricCard() = label("", 14f, TEXT_PRIMARY, true).apply { setLineSpacing(0f, 1.2f); setPadding(dp(14), dp(11), dp(14), dp(11)); background = rounded(SURFACE, 15f, BORDER) }
    private fun heroMetric(value: String, caption: String) = label("$value\n$caption", 20f, TEXT_PRIMARY, true).apply { gravity = Gravity.CENTER; setPadding(dp(5), dp(12), dp(5), dp(12)); background = rounded(SURFACE, 14f, BORDER); contentDescription = "$caption $value" }
    private fun actionButton(value: String, action: () -> Unit) = Button(this).apply { text = value; textSize = 12f; minHeight = dp(48); setTextColor(Color.WHITE); backgroundTintList = ColorStateList.valueOf(PRIMARY); setOnClickListener { runPressMotion(action) }; contentDescription = value }
    private fun compactButton(value: String, action: () -> Unit) = Button(this).apply { text = value; textSize = 12f; minHeight = dp(48); setTextColor(TEXT_PRIMARY); backgroundTintList = ColorStateList.valueOf(SURFACE_HIGH); setOnClickListener { runPressMotion(action) }; contentDescription = value }
    private fun ghostButton(value: String, action: () -> Unit) = Button(this).apply { text = value; textSize = 12f; minHeight = dp(48); setTextColor(TEXT_PRIMARY); backgroundTintList = ColorStateList.valueOf(Color.TRANSPARENT); setOnClickListener { runPressMotion(action) }; contentDescription = value }
    private fun weighted() = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply { marginStart = dp(3); marginEnd = dp(3) }
    private fun gridButton() = GridLayout.LayoutParams().apply { width = 0; height = dp(52); columnSpec = GridLayout.spec(GridLayout.UNDEFINED, 1f); setMargins(dp(3), dp(2), dp(3), dp(2)) }
    private fun margins(top: Int = 0, bottom: Int = 0, height: Int = ViewGroup.LayoutParams.WRAP_CONTENT) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, if (height >= 0) dp(height) else height).apply {
            topMargin = dp(top); bottomMargin = dp(bottom)
        }
    private fun rounded(fill: Int, radiusDp: Float, stroke: Int? = null) = GradientDrawable().apply { shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = dp(radiusDp.toInt()).toFloat(); if (stroke != null) setStroke(dp(1), stroke) }

    private fun requestStart() {
        val required = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION); if (Build.VERSION.SDK_INT >= 33) required += Manifest.permission.POST_NOTIFICATIONS
        val missing = required.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startRecordingService() else explainPermissionsThenRequest(missing)
    }
    private fun startRecordingService() {
        // Begin each navigation session in follow mode. Subsequent user pans remain respected
        // until the explicit Recenter control is tapped.
        if (::liveTrajectory.isInitialized) liveTrajectory.recenter()
        val intent = Intent(this, SensorLoggingService::class.java).setAction(SensorLoggingService.ACTION_START)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
    }
    private fun stopRecordingService() {
        startService(Intent(this, SensorLoggingService::class.java).setAction(SensorLoggingService.ACTION_STOP))
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    private fun explainPermissionsThenRequest(missing: List<String>) {
        AlertDialog.Builder(this).setTitle("Enable NavGhost live navigation")
            .setMessage("Precise location establishes trusted GNSS and calibrates NavGhost. Notifications keep local sensor processing active during a navigation session. No session is uploaded.")
            .setNegativeButton("NOT NOW", null)
            .setPositiveButton("CONTINUE") { _, _ -> pendingStart = true; requestPermissions(missing.toTypedArray(), REQUEST_PERMISSIONS) }
            .show()
    }
    private fun beginExport() {
        val directory = service?.latestSessionDirectory() ?: run { Toast.makeText(this, "No local session found", Toast.LENGTH_LONG).show(); return }
        beginExport(directory)
    }
    private fun beginExport(directory: File) {
        if (!directory.isDirectory) { Toast.makeText(this, "Linked session files are unavailable", Toast.LENGTH_LONG).show(); return }
        exportSource = directory
        startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type = "application/zip"; putExtra(Intent.EXTRA_TITLE, "${directory.name}.zip") }, REQUEST_EXPORT)
    }
    private fun zipDirectory(directory: File, zip: ZipOutputStream) {
        directory.listFiles()?.sortedBy { it.name }?.forEach { file -> if (file.isFile) { zip.putNextEntry(ZipEntry(file.name)); FileInputStream(file).use { it.copyTo(zip) }; zip.closeEntry() } }
    }
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun mapButton(value: String, action: () -> Unit) = Button(this).apply {
        text = value; textSize = 11f; minWidth = 0; minimumWidth = 0; setPadding(dp(4), 0, dp(4), 0)
        setTextColor(OVERLAY_PRIMARY); background = rounded(Color.argb(235, 8, 19, 30), 14f, Color.rgb(52, 77, 96))
        contentDescription = value
        setOnClickListener { runPressMotion(action) }
    }

    private fun View.runPressMotion(action: () -> Unit) {
        if (!isEnabled) return
        isEnabled = false
        animate().cancel()
        animate().scaleX(0.955f).scaleY(0.955f).alpha(0.82f).setDuration(65L).withEndAction {
            animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(115L)
                .setInterpolator(DecelerateInterpolator()).withEndAction {
                    isEnabled = true
                    action()
                }.start()
        }.start()
    }

    private fun meaningfulHaptic(feedback: Int) {
        if (hapticsEnabled) root.performHapticFeedback(feedback)
    }

    private fun maybeHapticTransition(mode: LocalizationMode) {
        val previous = lastLiveMode
        lastLiveMode = mode
        if (previous == null || previous == mode) return
        when {
            mode == LocalizationMode.IDR_ACTIVE -> meaningfulHaptic(HapticFeedbackConstants.LONG_PRESS)
            mode == LocalizationMode.GNSS_ACTIVE && previous in setOf(LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING) -> meaningfulHaptic(HapticFeedbackConstants.CONFIRM)
        }
    }

    private val BACKGROUND get() = if (darkTheme) Color.rgb(5, 13, 22) else Color.rgb(239, 246, 249)
    private val SURFACE get() = if (darkTheme) Color.rgb(14, 28, 42) else Color.rgb(255, 255, 255)
    private val SURFACE_HIGH get() = if (darkTheme) Color.rgb(25, 43, 59) else Color.rgb(221, 235, 241)
    private val BORDER get() = if (darkTheme) Color.rgb(44, 66, 84) else Color.rgb(190, 211, 220)
    private val TEXT_PRIMARY get() = if (darkTheme) Color.rgb(245, 249, 252) else Color.rgb(12, 31, 44)
    private val TEXT_SECONDARY get() = if (darkTheme) Color.rgb(190, 207, 220) else Color.rgb(54, 79, 94)
    private val TEXT_MUTED get() = if (darkTheme) Color.rgb(139, 161, 179) else Color.rgb(91, 113, 126)
    private val ACCENT get() = if (darkTheme) Color.rgb(74, 216, 181) else Color.rgb(8, 127, 145)

    companion object {
        private const val REQUEST_PERMISSIONS = 9001; private const val REQUEST_EXPORT = 9002
        private const val HUD_REFRESH_INTERVAL_MS = 500L
        // Deliver the newest estimator snapshot at its native ~10 Hz rate. The renderer keeps
        // independent camera/overlay gates, so this cannot create a camera-command backlog.
        private const val MAP_REFRESH_INTERVAL_MS = 100L
        private const val PERFORMANCE_MAP_REFRESH_INTERVAL_MS = 167L
        private const val PUBLIC_REPLAY_INTERVAL_MS = 120L
        private val PRIMARY = Color.rgb(24, 115, 158); private val HEALTHY = Color.rgb(23, 139, 110)
        private val WARNING = Color.rgb(214, 132, 38); private val CRITICAL = Color.rgb(190, 53, 67); private val DEMO = Color.rgb(95, 75, 181)
        private val OVERLAY_PRIMARY = Color.rgb(245, 249, 252); private val OVERLAY_SECONDARY = Color.rgb(190, 207, 220); private val OVERLAY_MUTED = Color.rgb(139, 161, 179)
    }
}
