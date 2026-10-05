package org.sih26168.idrlogger.product

import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ProductSettingsTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun dataStorePersistsUserFacingOptions() = runBlocking {
        val file = File(temporary.root, "settings.preferences_pb")
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val repository = ProductSettingsRepository.createForTest(file, scope)
        val expected = ProductSettings("LOCAL ENU", false, false, false, false, "DARK", false, true, true)
        repository.write(expected)
        assertEquals(expected, repository.read())
    }

    @Test fun legacyAutomaticRecenterPreferenceMigratesToManualFollow() = runBlocking {
        val file = File(temporary.root, "legacy_recenter.preferences_pb")
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val repository = ProductSettingsRepository.createForTest(file, scope)
        repository.write(ProductSettings(autoRecenter = true))
        assertFalse(repository.read().autoRecenter)
    }
}
