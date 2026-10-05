package org.sih26168.idrlogger.system

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import org.sih26168.idrlogger.model.SystemHealthSnapshot

class SystemHealthMonitor(private val context: Context) {
    fun snapshot(foregroundServiceActive: Boolean, loggerErrorCount: Int): SystemHealthSnapshot {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val temperatureTenthsC = battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            ?: Int.MIN_VALUE
        val thermal = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            thermalStatusLabel(context.getSystemService(PowerManager::class.java)?.currentThermalStatus)
        } else null
        return SystemHealthSnapshot(
            batteryPercent = if (level >= 0 && scale > 0) level * 100.0 / scale else null,
            batteryTemperatureC = if (temperatureTenthsC != Int.MIN_VALUE) temperatureTenthsC / 10.0 else null,
            thermalStatus = thermal,
            foregroundServiceActive = foregroundServiceActive,
            loggerErrorCount = loggerErrorCount,
        )
    }
}

internal fun thermalStatusLabel(value: Int?): String? = when (value) {
    null -> null
    PowerManager.THERMAL_STATUS_NONE -> "NONE"
    PowerManager.THERMAL_STATUS_LIGHT -> "LIGHT"
    PowerManager.THERMAL_STATUS_MODERATE -> "MODERATE"
    PowerManager.THERMAL_STATUS_SEVERE -> "SEVERE"
    PowerManager.THERMAL_STATUS_CRITICAL -> "CRITICAL"
    PowerManager.THERMAL_STATUS_EMERGENCY -> "EMERGENCY"
    PowerManager.THERMAL_STATUS_SHUTDOWN -> "SHUTDOWN"
    else -> "UNKNOWN_$value"
}
