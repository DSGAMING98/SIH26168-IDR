package org.sih26168.idrlogger.product

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

data class ProductSettings(
    val renderer: String = "AUTO",
    val headingUpCamera: Boolean = true,
    // Retained for settings-file compatibility only. Follow is now controlled by explicit map
    // gestures and the Recenter button, matching mainstream navigation apps.
    val autoRecenter: Boolean = false,
    val showTrail: Boolean = true,
    val showUncertainty: Boolean = true,
    val theme: String = "SYSTEM",
    val haptics: Boolean = true,
    val telemetryEnabled: Boolean = false,
    val performanceMode: Boolean = false,
)

/** DataStore contains display/connectivity preferences only—never estimator tuning parameters. */
class ProductSettingsRepository private constructor(private val dataStore: DataStore<Preferences>) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    fun load(callback: (ProductSettings) -> Unit) = scope.launch { callback(read()) }
    suspend fun read(): ProductSettings = dataStore.data.first().let(::decode)
    fun save(value: ProductSettings) = scope.launch { write(value) }
    suspend fun write(value: ProductSettings) { dataStore.edit { p ->
        p[RENDERER] = value.renderer; p[HEADING_UP] = value.headingUpCamera; p[AUTO_RECENTER] = value.autoRecenter
        p[SHOW_TRAIL] = value.showTrail; p[SHOW_UNCERTAINTY] = value.showUncertainty; p[THEME] = value.theme
        p[HAPTICS] = value.haptics; p[TELEMETRY] = value.telemetryEnabled; p[PERFORMANCE] = value.performanceMode
    } }

    companion object {
        @Volatile private var instance: ProductSettingsRepository? = null
        private val RENDERER = stringPreferencesKey("renderer")
        private val HEADING_UP = booleanPreferencesKey("heading_up")
        private val AUTO_RECENTER = booleanPreferencesKey("auto_recenter")
        private val SHOW_TRAIL = booleanPreferencesKey("show_trail")
        private val SHOW_UNCERTAINTY = booleanPreferencesKey("show_uncertainty")
        private val THEME = stringPreferencesKey("theme")
        private val HAPTICS = booleanPreferencesKey("haptics")
        private val TELEMETRY = booleanPreferencesKey("telemetry_enabled")
        private val PERFORMANCE = booleanPreferencesKey("performance_mode")
        fun create(context: Context): ProductSettingsRepository = instance ?: synchronized(this) {
            instance ?: ProductSettingsRepository(PreferenceDataStoreFactory.create {
                context.applicationContext.preferencesDataStoreFile("product_settings")
            }).also { instance = it }
        }
        fun createForTest(file: File, scope: CoroutineScope) = ProductSettingsRepository(PreferenceDataStoreFactory.create(scope = scope) { file })
        private fun decode(p: Preferences) = ProductSettings(p[RENDERER] ?: "AUTO", p[HEADING_UP] ?: true,
            false, p[SHOW_TRAIL] ?: true, p[SHOW_UNCERTAINTY] ?: true,
            p[THEME] ?: "SYSTEM", p[HAPTICS] ?: true, p[TELEMETRY] ?: false, p[PERFORMANCE] ?: false)
    }
}
