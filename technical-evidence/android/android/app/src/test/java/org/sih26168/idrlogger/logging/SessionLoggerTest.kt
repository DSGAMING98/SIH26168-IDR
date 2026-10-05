package org.sih26168.idrlogger.logging

import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SessionLoggerTest {
    @Test
    fun repeatedStartsNeverReuseOrOverwriteSessionDirectory() {
        val root = Files.createTempDirectory("idr-session-test").toFile()
        try {
            val first = createUniqueSessionDirectory(root, "same_second_phone_session")
            val second = createUniqueSessionDirectory(root, "same_second_phone_session")
            assertNotEquals(first, second)
            assertEquals("same_second_phone_session", first.name)
            assertEquals("same_second_phone_session_1", second.name)
        } finally {
            root.deleteRecursively()
        }
    }
}
