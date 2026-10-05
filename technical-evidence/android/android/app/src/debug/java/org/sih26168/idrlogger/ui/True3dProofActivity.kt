package org.sih26168.idrlogger.ui

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.TextView
import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.ConfidenceLevel
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.TrajectoryPoint

/** Isolated Gate A renderer proof; no service, estimator, GNSS or route input is connected. */
class True3dProofActivity : Activity() {
    private lateinit var surface: True3dMapSurface

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)
        val status = TextView(this).apply {
            setTextColor(Color.WHITE); setBackgroundColor(Color.argb(210, 5, 14, 24)); textSize = 14f
            setPadding(24, 18, 24, 18); text = "GATE A • TRUE 3D VECTOR PROOF\nLoading OpenFreeMap buildings…"
        }
        surface = True3dMapSurface(this, savedInstanceState?.getBundle("true3d")) {
            status.text = "GATE A • TRUE 3D VECTOR PROOF\n${it.primaryLabel} • ${it.detailLabel}\n${it.attribution.orEmpty()}"
        }
        root.addView(surface, FrameLayout.LayoutParams(-1, -1))
        root.addView(status, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))
        setContentView(root)
        surface.show(proofSnapshot())
    }

    override fun onStart() { super.onStart(); surface.onStart() }
    override fun onResume() { super.onResume(); surface.onResume() }
    override fun onPause() { surface.onPause(); super.onPause() }
    override fun onStop() { surface.onStop(); super.onStop() }
    override fun onDestroy() { surface.onDestroy(); super.onDestroy() }
    override fun onLowMemory() { super.onLowMemory(); surface.onLowMemory() }
    override fun onSaveInstanceState(outState: Bundle) {
        val map = Bundle(); surface.onSaveInstanceState(map); outState.putBundle("true3d", map); super.onSaveInstanceState(outState)
    }

    private fun proofSnapshot(): NavigationSnapshot {
        val points = (0..70).map { index ->
            TrajectoryPoint(index * 1.8, index * 0.38, if (index < 42) LocalizationMode.GNSS_ACTIVE else LocalizationMode.IDR_ACTIVE)
        }
        return NavigationSnapshot(
            state = NavigationState(
                latitudeDeg = 12.97172, longitudeDeg = 77.59478,
                eastM = points.last().eastM, northM = points.last().northM,
                speedMps = 13.4, headingDeg = 78.0, horizontalUncertaintyM = 8.0,
                confidence = ConfidenceLevel.HIGH, localizationMode = LocalizationMode.IDR_ACTIVE,
                alignmentState = AlignmentState.READY, motionState = MotionState.MOVING,
                message = "Isolated true-3D renderer proof",
            ),
            trajectory = points,
            isDemoReplay = true,
        )
    }
}
