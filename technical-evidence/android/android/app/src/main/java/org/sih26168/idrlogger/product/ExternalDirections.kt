package org.sih26168.idrlogger.product

enum class DirectionsTravelMode(val urlValue: String, val label: String) {
    DRIVING("driving", "Drive"),
    WALKING("walking", "Walk"),
    TWO_WHEELER("two-wheeler", "Two-wheeler"),
}

/**
 * Builds the official Google Maps universal directions URL. Origin is intentionally omitted so
 * Google Maps uses the device's live location and can enter turn-by-turn voice guidance. This
 * handoff is presentation-only and cannot feed a route or Google location back into NavGhost.
 */
object ExternalDirections {
    fun url(destinationLatitude: Double, destinationLongitude: Double, mode: DirectionsTravelMode): String {
        require(destinationLatitude.isFinite() && destinationLatitude in -90.0..90.0)
        require(destinationLongitude.isFinite() && destinationLongitude in -180.0..180.0)
        return "https://www.google.com/maps/dir/?api=1" +
            "&destination=$destinationLatitude,$destinationLongitude" +
            "&travelmode=${mode.urlValue}&dir_action=navigate"
    }
}
