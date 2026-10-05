package org.sih26168.idrlogger.product

import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.ui.MainActivity

/** Requires a configured debug backend; skipped in ordinary offline test builds. */
@Suppress("DEPRECATION")
class GeoMeshEndToEndInstrumentedTest {
    @Test fun androidRequestReachesBackendAndResultAppearsInGeoMeshUi() {
        assumeTrue("Build has no GeoMesh backend", BuildConfig.GEOMESH_CONFIGURED)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val unique = "Physical E2E ${UUID.randomUUID()}"
        val snapshot = NavigationSnapshot(state = NavigationState(sequenceId = 77, latitudeDeg = 12.9716, longitudeDeg = 77.5946))
        val repository = GeoMeshRepository(context)
        val createdLatch = CountDownLatch(1); var zone: GeoFenceEntity? = null
        repository.create(snapshot, GeoMeshCategory.ROAD_BLOCK, unique) {
            zone = it.getOrThrow(); createdLatch.countDown()
        }
        assertTrue(createdLatch.await(5, TimeUnit.SECONDS))
        val latch = CountDownLatch(1); var sync: GeoMeshSyncResult? = null
        repository.sync(snapshot) { sync = it; latch.countDown() }
        assertTrue(latch.await(15, TimeUnit.SECONDS)); assertTrue(sync!!.state in setOf(GeoMeshConnectionState.CONNECTED, GeoMeshConnectionState.NO_HAZARD_ZONES))
        val stored = NavGhostDatabase.get(context).geoMeshDao().byId(zone!!.id)
        assertNotNull(stored); assertEquals("SYNCED", stored.syncState)

        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        try {
            instrumentation.runOnMainSync {
                find(activity.window.decorView) { it is TextView && it.text.toString() == "▦\nHOME" }!!.performClick()
                find(activity.window.decorView) { it is TextView && it.text.toString() == "GEOMESH • OFFLINE HAZARD ZONES" }!!.performClick()
                val product = MainActivity::class.java.getDeclaredField("productExperience").apply { isAccessible = true }.get(activity) as ProductExperience
                product.refreshGeoMesh()
            }
            Thread.sleep(1200)
            assertNotNull("Backend zone was not rendered", find(activity.window.decorView) { it is TextView && it.text.toString().contains(unique) })
        } finally {
            NavGhostDatabase.get(context).geoMeshDao().deleteZone(zone!!.id)
            instrumentation.runOnMainSync { activity.finish() }
        }
    }

    private fun find(view: View, predicate: (View) -> Boolean): View? {
        if (predicate(view)) return view
        if (view is ViewGroup) for (i in 0 until view.childCount) find(view.getChildAt(i), predicate)?.let { return it }
        return null
    }
}
