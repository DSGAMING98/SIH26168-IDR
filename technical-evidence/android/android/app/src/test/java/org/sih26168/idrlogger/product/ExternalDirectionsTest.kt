package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExternalDirectionsTest {
    @Test
    fun buildsOfficialVoiceNavigationHandoffWithoutInjectingAnOrigin() {
        val url = ExternalDirections.url(12.9716, 77.5946, DirectionsTravelMode.TWO_WHEELER)
        assertEquals(
            "https://www.google.com/maps/dir/?api=1&destination=12.9716,77.5946&travelmode=two-wheeler&dir_action=navigate",
            url,
        )
        assertFalse(url.contains("origin="))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsInvalidDestination() {
        ExternalDirections.url(95.0, 77.0, DirectionsTravelMode.DRIVING)
    }

    @Test
    fun allModesUseSupportedMapsUrlValues() {
        assertTrue(DirectionsTravelMode.entries.map { it.urlValue }.toSet() == setOf("driving", "walking", "two-wheeler"))
    }
}
