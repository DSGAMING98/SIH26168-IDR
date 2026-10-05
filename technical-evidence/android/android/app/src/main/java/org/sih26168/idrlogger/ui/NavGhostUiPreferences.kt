package org.sih26168.idrlogger.ui

import android.content.Context
import android.content.res.Configuration

enum class VisualTheme { SYSTEM, DARK, LIGHT }

/** App-owned presentation preferences. No engine or localization state is stored here. */
class NavGhostUiPreferences(context: Context) {
    private val preferences = context.getSharedPreferences("navghost_ui", Context.MODE_PRIVATE)

    fun theme(): VisualTheme = runCatching {
        VisualTheme.valueOf(preferences.getString(KEY_THEME, VisualTheme.SYSTEM.name).orEmpty())
    }.getOrDefault(VisualTheme.SYSTEM)

    fun setTheme(value: VisualTheme) = preferences.edit().putString(KEY_THEME, value.name).apply()
    fun hapticsEnabled(): Boolean = preferences.getBoolean(KEY_HAPTICS, true)
    fun setHapticsEnabled(value: Boolean) = preferences.edit().putBoolean(KEY_HAPTICS, value).apply()

    companion object {
        private const val KEY_THEME = "theme"
        private const val KEY_HAPTICS = "haptics"

        fun isDark(theme: VisualTheme, uiMode: Int): Boolean = when (theme) {
            VisualTheme.DARK -> true
            VisualTheme.LIGHT -> false
            VisualTheme.SYSTEM -> uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        }
    }
}
