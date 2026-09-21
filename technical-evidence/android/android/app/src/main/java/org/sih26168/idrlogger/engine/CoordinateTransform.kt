package org.sih26168.idrlogger.engine

import kotlin.math.PI
import kotlin.math.cos

data class LocalPoint(val eastM: Double, val northM: Double)

data class GeodeticPoint(val latitudeDeg: Double, val longitudeDeg: Double)

/** Short-range local tangent approximation; not a survey-grade CRS transformation. */
class CoordinateTransform(
    val originLatitudeDeg: Double,
    val originLongitudeDeg: Double,
) {
    init {
        require(originLatitudeDeg.isFinite() && originLatitudeDeg in -90.0..90.0)
        require(originLongitudeDeg.isFinite() && originLongitudeDeg in -180.0..180.0)
    }

    private val latitudeRad = Math.toRadians(originLatitudeDeg)
    private val longitudeScale = EARTH_MEAN_RADIUS_M * cos(latitudeRad)

    fun toLocal(latitudeDeg: Double, longitudeDeg: Double): LocalPoint {
        require(latitudeDeg.isFinite() && longitudeDeg.isFinite())
        return LocalPoint(
            eastM = Math.toRadians(wrapLongitude(longitudeDeg - originLongitudeDeg)) * longitudeScale,
            northM = Math.toRadians(latitudeDeg - originLatitudeDeg) * EARTH_MEAN_RADIUS_M,
        )
    }

    fun toGeodetic(eastM: Double, northM: Double): GeodeticPoint {
        require(eastM.isFinite() && northM.isFinite())
        val latitude = originLatitudeDeg + Math.toDegrees(northM / EARTH_MEAN_RADIUS_M)
        val longitude = originLongitudeDeg + Math.toDegrees(eastM / longitudeScale)
        return GeodeticPoint(latitude, wrapLongitude(longitude))
    }

    companion object {
        const val EARTH_MEAN_RADIUS_M = 6_371_008.8

        private fun wrapLongitude(value: Double): Double {
            var result = (value + 180.0) % 360.0
            if (result < 0.0) result += 360.0
            return result - 180.0
        }
    }
}

internal fun wrapAngleRad(value: Double): Double {
    var result = (value + PI) % (2.0 * PI)
    if (result < 0.0) result += 2.0 * PI
    return result - PI
}

internal fun headingRadToDegrees(value: Double): Double {
    val degrees = Math.toDegrees(value) % 360.0
    return if (degrees < 0.0) degrees + 360.0 else degrees
}
