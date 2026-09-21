package org.sih26168.idrlogger.core

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import org.sih26168.idrlogger.logging.DeviceSensorInfo
import org.sih26168.idrlogger.logging.toDeviceSensorInfo
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.SensorKind
import org.sih26168.idrlogger.model.TimedSensorValue

class SensorRepository(
    context: Context,
    private val buffer: CausalSensorBuffer,
    private val rateTracker: SensorRateTracker,
    private val onRawSample: (TimedSensorValue) -> Unit,
    private val onError: (String) -> Unit,
) : SensorEventListener {
    private val sensorManager = context.getSystemService(SensorManager::class.java)
    private val sensorMap = linkedMapOf(
        SensorKind.ACCELEROMETER to sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER),
        SensorKind.GYROSCOPE to sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE),
        SensorKind.MAGNETOMETER to sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD),
        SensorKind.GRAVITY to sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY),
        SensorKind.ROTATION_VECTOR to sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR),
    )
    private var thread: HandlerThread? = null
    private var running = false

    val sensorInfo: List<DeviceSensorInfo> = sensorMap.map { (kind, sensor) ->
        sensor?.toDeviceSensorInfo(kind.csvName) ?: DeviceSensorInfo(kind.csvName, false, null, null, null, null)
    }

    fun availability(gpsProvider: Boolean) = SensorAvailability(
        accelerometer = sensorMap[SensorKind.ACCELEROMETER] != null,
        gyroscope = sensorMap[SensorKind.GYROSCOPE] != null,
        magnetometer = sensorMap[SensorKind.MAGNETOMETER] != null,
        gravity = sensorMap[SensorKind.GRAVITY] != null,
        rotationVector = sensorMap[SensorKind.ROTATION_VECTOR] != null,
        gpsProvider = gpsProvider,
    )

    fun start() {
        if (running) return
        running = true
        thread = HandlerThread("IdrNativeSensors").also { it.start() }
        val handler = Handler(thread!!.looper)
        sensorMap.forEach { (kind, sensor) ->
            if (sensor == null) {
                onError("SENSOR_MISSING:${kind.csvName}")
            } else if (!sensorManager.registerListener(this, sensor, REQUESTED_SAMPLING_PERIOD_US, 0, handler)) {
                onError("SENSOR_REGISTER_FAILED:${kind.csvName}")
            }
        }
    }

    fun stop() {
        if (!running) return
        running = false
        sensorManager.unregisterListener(this)
        thread?.quitSafely()
        thread = null
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (!running) return
        val kind = when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> SensorKind.ACCELEROMETER
            Sensor.TYPE_GYROSCOPE -> SensorKind.GYROSCOPE
            Sensor.TYPE_MAGNETIC_FIELD -> SensorKind.MAGNETOMETER
            Sensor.TYPE_GRAVITY -> SensorKind.GRAVITY
            Sensor.TYPE_ROTATION_VECTOR -> SensorKind.ROTATION_VECTOR
            else -> return
        }
        val values = if (kind == SensorKind.ROTATION_VECTOR) {
            val quaternion = FloatArray(4)
            SensorManager.getQuaternionFromVector(quaternion, event.values)
            listOf(quaternion[1].toDouble(), quaternion[2].toDouble(), quaternion[3].toDouble(), quaternion[0].toDouble())
        } else {
            event.values.take(3).map(Float::toDouble)
        }
        val sample = TimedSensorValue(kind, event.timestamp, values, event.accuracy)
        if (!buffer.add(sample)) {
            onError("OUT_OF_ORDER_SENSOR:${kind.csvName}")
            return
        }
        rateTracker.record(kind, event.timestamp)
        onRawSample(sample)
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    companion object {
        const val REQUESTED_SAMPLING_PERIOD_US = 20_000 // approximately 50 Hz request; measured rate is logged
    }
}
