package org.sih26168.idrlogger.product

import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Button
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.sih26168.idrlogger.ui.MainActivity
import org.sih26168.idrlogger.service.SensorLoggingService

@Suppress("DEPRECATION")
class ProductExperienceScreenTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: MainActivity
    @Before fun start() {
        activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        Thread.sleep(1200)
    }
    @After fun stop() { instrumentation.runOnMainSync { service()?.takeIf { it.status().recording }?.stop(); activity.finish() } }

    @Test fun fiveProductPagesSettingsAndRealTripLifecycleWork() {
        tapDescription("⌾ MAP"); assertNotNull(findText("START NAVIGATION"))
        tapDescription("▦ HOME"); assertNotNull(findText("DASHBOARD"))
        tapText("GEOMESH • OFFLINE HAZARD ZONES"); assertNotNull(findText("NAVGHOST GEOMESH")); assertNotNull(findText("CREATE A LOCAL ZONE"))
        tapDescription("▦ HOME")
        instrumentation.runOnMainSync { service()?.takeIf { it.status().recording }?.stop() }
        val navigationButton = findText("START NAVIGATION") as Button
        instrumentation.runOnMainSync { navigationButton.performClick() }
        Thread.sleep(3500); assertTrue(service()?.status()?.recording == true)
        instrumentation.runOnMainSync { navigationButton.performClick() }; Thread.sleep(1200)
        assertTrue(service()?.status()?.recording == false)
        val trips = NavGhostDatabase.get(activity).tripDao().allTrips()
        assertTrue(trips.isNotEmpty()); assertEquals("COMPLETED", trips.first().status)

        tapDescription("⌖ NEARBY"); assertNotNull(findText("NEARBY")); assertNotNull(findText("SEARCH ORIGIN"))
        assertNotNull(findText("OpenStreetMap / Overpass • from NavGhost's current estimate"))
        tapDescription("◷ TRIPS"); Thread.sleep(1000); assertNotNull(findText("TRIP HISTORY")); assertNotNull(findText("VIEW DETAILS"))
        tapDescription("⌁ INSIGHTS"); assertNotNull(findText("INSIGHTS")); assertNotNull(findText("NAVIGATION RESILIENCE"))
        tapDescription("▦ HOME"); tapText("ENGINEERING"); assertNotNull(findText("SYSTEM HEALTH")); assertNotNull(findText("FIELD TEST"))
        tapText("⚙"); assertNotNull(findText("SETTINGS"))
        val before = runBlocking { ProductSettingsRepository.create(activity).read() }
        tapText("SHOW TRAIL • ${if (before.showTrail) "ON" else "OFF"}")
        Thread.sleep(500)
        val settings = runBlocking { ProductSettingsRepository.create(activity).read() }
        assertEquals(!before.showTrail, settings.showTrail)
        tapDescription("▦ HOME"); tapText("JUDGE DEMO"); assertNotNull(findText("NavGhost Demo"))
    }

    private fun tapDescription(description: String) = instrumentation.runOnMainSync {
        val view = find(activity.window.decorView) { it.contentDescription?.toString() == description }
        assertNotNull("Missing $description", view); view!!.performClick()
    }
    private fun tapText(value: String) = instrumentation.runOnMainSync {
        val view = find(activity.window.decorView) { it is TextView && it.text.toString() == value }
        assertNotNull("Missing $value", view); view!!.performClick()
    }
    private fun findText(value: String): View? = find(activity.window.decorView) { it is TextView && it.text.toString() == value }
    private fun service(): SensorLoggingService? = MainActivity::class.java.getDeclaredField("service").apply { isAccessible = true }.get(activity) as? SensorLoggingService
    private fun find(view: View, predicate: (View) -> Boolean): View? {
        if (predicate(view)) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) find(view.getChildAt(index), predicate)?.let { return it }
        return null
    }
}
