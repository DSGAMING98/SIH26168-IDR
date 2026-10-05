package org.sih26168.idrlogger.ui

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.TextView
import com.google.android.gms.maps3d.model.Map3DMode
import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.map.MapCoordinateProjector
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/** Debug-only physical renderer proof. No location provider or estimator input is connected. */
class Google3dProofActivity : Activity() {
    private lateinit var surface: Google3dMapSurface
    private lateinit var statusView: TextView
    private var mapModeLabel = "HYBRID"
    private val replayHandler = Handler(Looper.getMainLooper())
    private var replayFrame = 0
    private val replayRoute = (0..1_999).map { index ->
        TrajectoryPoint(
            eastM = index * 1.2,
            northM = 90.0 * sin(index / 95.0) + 18.0 * sin(index / 23.0),
            localizationMode = if (index < 1_250) LocalizationMode.GNSS_ACTIVE else LocalizationMode.IDR_ACTIVE,
        )
    }
    private val replay = object : Runnable {
        override fun run() {
            surface.show(proofSnapshot(800 + replayFrame % 1_150))
            replayFrame += 1
            if (replayFrame % 50 == 0) {
                val stats = surface.performanceStats()
                val line = String.format(
                    java.util.Locale.US,
                    "%s offered %.1f Hz • visual %.1f Hz • camera %.1f Hz • trail %.1f Hz • ring %.1f Hz • coalesced %d",
                    mapModeLabel,
                    stats.offeredSnapshotHz,
                    stats.renderedSnapshotHz,
                    stats.cameraCommandHz,
                    stats.trajectoryUpdateHz,
                    stats.uncertaintyUpdateHz,
                    stats.supersededSnapshots,
                )
                Log.i("NavGhostPerf", line)
                statusView.text = "PHYSICAL QA • 10 HZ SYNTHETIC PERFORMANCE REPLAY • NOT LIVE\n$line"
            }
            replayHandler.postDelayed(this, 100L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)
        mapModeLabel = if (intent.getBooleanExtra("roadmap", false)) "ROADMAP" else "HYBRID"
        statusView = TextView(this).apply {
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.argb(210, 5, 14, 24))
            textSize = 14f
            setPadding(24, 18, 24, 18)
            text = "PHYSICAL QA • 10 HZ SYNTHETIC PERFORMANCE REPLAY • NOT LIVE\nLoading Google 3D…"
        }
        surface = Google3dMapSurface(this) {
            statusView.text = "PHYSICAL QA • 10 HZ SYNTHETIC PERFORMANCE REPLAY • NOT LIVE\n${it.primaryLabel} • ${it.detailLabel}\n${it.attribution.orEmpty()}"
        }
        surface.setPerformanceProofMapMode(if (mapModeLabel == "ROADMAP") Map3DMode.ROADMAP else Map3DMode.HYBRID)
        root.addView(surface, FrameLayout.LayoutParams(-1, -1))
        root.addView(statusView, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))
        setContentView(root)
        surface.show(proofSnapshot(800))
    }

    override fun onStart() { super.onStart(); surface.onStart() }
    override fun onResume() { super.onResume(); surface.onResume(); replayHandler.post(replay) }
    override fun onPause() { replayHandler.removeCallbacks(replay); surface.onPause(); super.onPause() }
    override fun onStop() { surface.onStop(); super.onStop() }
    override fun onDestroy() { replayHandler.removeCallbacksAndMessages(null); surface.onDestroy(); super.onDestroy() }
    override fun onLowMemory() { super.onLowMemory(); surface.onLowMemory() }
    private fun proofSnapshot(pointCount: Int): NavigationSnapshot {
        val points = replayRoute.subList(0, pointCount.coerceIn(2, replayRoute.size))
        val point = points.last()
        val previous = points[points.lastIndex - 1]
        val location = MapCoordinateProjector.fromCurrentEnginePosition(
            point.eastM, point.northM, 0.0, 0.0, 12.97160, 77.59460,
        )
        val heading = Math.toDegrees(atan2(point.eastM - previous.eastM, point.northM - previous.northM))
        return NavigationSnapshot(
            state = NavigationState(
                sequenceId = replayFrame.toLong(),
                monotonicTimestampNs = System.nanoTime(),
                latitudeDeg = location.latitudeDeg,
                longitudeDeg = location.longitudeDeg,
                eastM = point.eastM,
                northM = point.northM,
                speedMps = 13.4,
                headingDeg = (heading + 360.0) % 360.0,
                horizontalUncertaintyM = 8.0 + 1.5 * cos(replayFrame / 30.0),
                confidence = ConfidenceLevel.HIGH,
                localizationMode = LocalizationMode.IDR_ACTIVE,
                alignmentState = AlignmentState.READY,
                motionState = MotionState.MOVING,
                message = "Debug-only synthetic renderer proof",
            ),
            trajectory = points,
            isDemoReplay = true,
        )
    }
}
