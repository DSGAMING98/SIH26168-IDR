package org.sih26168.idrlogger.ui

import android.content.res.Configuration
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NavGhostUiPreferencesTest {
    @Test fun explicitThemesOverrideSystemAndSystemTracksNightMask() {
        assertTrue(NavGhostUiPreferences.isDark(VisualTheme.DARK, Configuration.UI_MODE_NIGHT_NO))
        assertFalse(NavGhostUiPreferences.isDark(VisualTheme.LIGHT, Configuration.UI_MODE_NIGHT_YES))
        assertTrue(NavGhostUiPreferences.isDark(VisualTheme.SYSTEM, Configuration.UI_MODE_NIGHT_YES))
        assertFalse(NavGhostUiPreferences.isDark(VisualTheme.SYSTEM, Configuration.UI_MODE_NIGHT_NO))
    }
}
