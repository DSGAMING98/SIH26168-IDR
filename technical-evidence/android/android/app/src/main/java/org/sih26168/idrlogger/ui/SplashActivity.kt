package org.sih26168.idrlogger.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.accessibility.AccessibilityManager
import org.sih26168.idrlogger.R

class SplashActivity : Activity() {
    private var transitionStarted = false

    override fun onCreate(savedInstanceState: Bundle?) {
        setTheme(R.style.AppThemeSplash)
        super.onCreate(savedInstanceState)
        window.statusBarColor = NAVY
        window.navigationBarColor = NAVY
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION

        val splash = NavGhostSplashView(this).apply {
            contentDescription = getString(R.string.splash_description)
        }
        setContentView(splash)
        splash.start(reducedMotionRequested()) { openMainScreen() }
    }

    private fun reducedMotionRequested(): Boolean {
        val animationScale = runCatching {
            Settings.Global.getFloat(contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f)
        }.getOrDefault(1f)
        val accessibility = getSystemService(ACCESSIBILITY_SERVICE) as? AccessibilityManager
        return animationScale == 0f || accessibility?.isTouchExplorationEnabled == true
    }

    private fun openMainScreen() {
        if (transitionStarted || isFinishing || isDestroyed) return
        transitionStarted = true
        startActivity(
            Intent(this, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            )
        )
        overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
        finish()
    }

    companion object {
        private const val NAVY = 0xFF060D16.toInt()
    }
}
