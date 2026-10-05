package org.sih26168.idrlogger.ui

import android.content.Intent
import android.graphics.Bitmap
import android.os.Handler
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Before
import org.junit.After
import org.junit.Test
import android.widget.Button
import android.widget.TextView
import org.maplibre.android.maps.MapLibreMap
import java.io.File
import org.sih26168.idrlogger.engine.*
import org.sih26168.idrlogger.model.LoggerStatus

/** Test-APK-only fixtures. Never recorded, emitted through telemetry, or exposed by the release app. */
@Suppress("DEPRECATION")
class CinematicScreenTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: MainActivity
    private fun field(name: String): Any? = MainActivity::class.java.getDeclaredField(name).apply { isAccessible = true }.get(activity)
    private fun ui(action: () -> Unit) = instrumentation.runOnMainSync(action)
    private fun capture(name: String) {
        instrumentation.waitForIdleSync()
        val directory = File(activity.getExternalFilesDir(null), "true3d-qa").apply { mkdirs() }
        File(directory, "$name.png").outputStream().use {
            instrumentation.uiAutomation.takeScreenshot().compress(Bitmap.CompressFormat.PNG, 100, it)
        }
    }
    @Before fun setUp() {
        activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        Thread.sleep(1500)
        ui { (field("uiHandler") as Handler).removeCallbacksAndMessages(null) }
    }
    @After fun tearDown() { ui { activity.finish() } }

    @Test fun testLiveHudAndCinematicStateScreens() {
        capture("01-waiting-real-ui")
        val surface = field("liveTrajectory") as NavGhostMapSurface
        val render = MainActivity::class.java.getDeclaredMethod("renderLive", NavigationSnapshot::class.java, LoggerStatus::class.java)
            .apply { isAccessible = true }
        var snapshot = NavigationSnapshot(state = NavigationState(sequenceId = 1, latitudeDeg = 12.9716,
            longitudeDeg = 77.5946, speedMps = 13.33, headingDeg = 0.0, horizontalUncertaintyM = 7.4,
            confidence = ConfidenceLevel.HIGH, alignmentState = AlignmentState.READY, motionState = MotionState.MOVING,
            localizationMode = LocalizationMode.GNSS_ACTIVE, mlState = MlRuntimeState.ML_ACCEPTED,
            message = "UI TEST FIXTURE • NOT LIVE"), isDemoReplay = true)
        fun show() = ui {
            render.invoke(activity, snapshot, null)
            surface.show(snapshot)
            (field("contextLabel") as TextView).text = "UI TEST FIXTURE • NOT LIVE"
        }
        repeat(60) { show(); Thread.sleep(250) }
        capture("01-urban-dense-buildings")
        show()
        instrumentation.waitForIdleSync()
        ui {
            assertTrue("Map should dominate usable content", surface.height > activity.window.decorView.height * 0.60)
            assertTrue((field("modeHero") as TextView).text.contains("GNSS ACTIVE"))
            assertEquals("3D CHASE", (field("mapOrientationButton") as Button).text.toString())
            assertTrue(surface.layerLabel() in setOf("GOOGLE 3D", "MAPLIBRE 3D"))
            for (name in listOf("modeHero", "satelliteHud", "liveSecondary", "speedHero", "uncertaintyHero", "telemetryIndicator")) {
                val view = field(name) as TextView
                val layout = view.layout
                if (layout == null) {
                    assertTrue("HUD text must still have measured bounds: $name", view.measuredWidth > 0 && view.measuredHeight > 0)
                    continue
                }
                assertTrue("HUD text must fit vertically: $name", layout.height <= view.height - view.compoundPaddingTop - view.compoundPaddingBottom)
                for (line in 0 until layout.lineCount) {
                    assertEquals("HUD text must not be ellipsized: $name", 0, layout.getEllipsisCount(line))
                    assertTrue("HUD text must fit horizontally: $name", layout.getLineWidth(line) <= view.width - view.compoundPaddingLeft - view.compoundPaddingRight + 1)
                }
            }
        }
        if (surface.layerLabel() == "MAPLIBRE 3D") {
            val true3d = NavGhostMapSurface::class.java.getDeclaredField("true3dView").apply { isAccessible = true }.get(surface) as True3dMapSurface
            val vectorMap = True3dMapSurface::class.java.getDeclaredField("map").apply { isAccessible = true }.get(true3d) as? MapLibreMap
            assertNotNull("MapLibre true-3D renderer must initialize", vectorMap)
            ui { true3d.show(snapshot); true3d.recenter() }
            Thread.sleep(2500)
            ui {
                val tilt = vectorMap!!.cameraPosition.tilt
                assertTrue("True-3D camera pitch must remain finite", tilt.isFinite())
                // Some OEMs suppress map camera animation while the device is locked. Pure camera
                // policy tests cover the target pitch; validate the rendered chase frame when active.
                if (tilt > 0.0) {
                    assertTrue("True-3D camera pitch must expose building faces", tilt in 58.0..72.0)
                    val pixel = vectorMap.projection.toScreenLocation(org.maplibre.android.geometry.LatLng(12.9716, 77.5946))
                    val fraction = pixel.y.toDouble() / surface.height
                    // OEM system-bar/inset differences can shift the measured map surface slightly.
                    assertTrue("Marker must remain in the lower chase viewport: $fraction", fraction in 0.60..0.82)
                }
            }
        } else {
            val google3d = NavGhostMapSurface::class.java.getDeclaredField("google3dView").apply { isAccessible = true }.get(surface) as Google3dMapSurface
            val map3d = Google3dMapSurface::class.java.getDeclaredField("map").apply { isAccessible = true }.get(google3d)
            assertNotNull("Google 3D must finish authentication and initialize", map3d)
        }
        capture("02-forward-road-perspective")

        snapshot = snapshot.copy(state = snapshot.state.copy(headingDeg = 72.0, speedMps = 11.0))
        repeat(8) { show(); Thread.sleep(180) }
        capture("03-turning-perspective")
        snapshot = snapshot.copy(state = snapshot.state.copy(speedMps = 3.0, headingDeg = 74.0))
        repeat(8) { show(); Thread.sleep(180) }
        capture("04-steady-low-speed")
        snapshot = snapshot.copy(state = snapshot.state.copy(speedMps = 31.0, headingDeg = 78.0))
        repeat(8) { show(); Thread.sleep(180) }
        capture("05-high-speed-lookahead")
        snapshot = snapshot.copy(state = snapshot.state.copy(speedMps = 0.0, motionState = MotionState.LIKELY_STATIONARY, headingDeg = 220.0))
        repeat(14) { show(); Thread.sleep(180) }
        capture("06-stationary-stable")

        snapshot = snapshot.copy(state = snapshot.state.copy(speedMps = 13.33, motionState = MotionState.MOVING,
            localizationMode = LocalizationMode.IDR_ACTIVE, drDurationSeconds = 30.0, horizontalUncertaintyM = 32.0))
        repeat(8) { show(); Thread.sleep(180) }
        capture("07-idr-active-amber")
        snapshot = snapshot.copy(state = snapshot.state.copy(localizationMode = LocalizationMode.GNSS_VERIFYING))
        repeat(8) { show(); Thread.sleep(180) }
        capture("08-gnss-verifying-violet")
        snapshot = snapshot.copy(state = snapshot.state.copy(localizationMode = LocalizationMode.GNSS_RECOVERING))
        repeat(8) { show(); Thread.sleep(180) }
        capture("09-gnss-recovering-violet")

        // Provider authentication/fallback policy is covered by deterministic unit tests. Avoid
        // cycling network-backed tile providers here: OEM lock screens can indefinitely defer a
        // map transition even though both renderers initialized successfully earlier in the run.
        ui { (field("recenterButton") as Button).performClick() }
        repeat(8) { show(); Thread.sleep(250) }
        ui { assertTrue(surface.isCinematic()); assertTrue(surface.isFollowing()) }
        capture("10-smooth-recenter")
    }
}
