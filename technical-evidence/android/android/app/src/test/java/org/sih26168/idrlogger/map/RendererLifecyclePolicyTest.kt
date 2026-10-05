package org.sih26168.idrlogger.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RendererLifecyclePolicyTest {
    @Test fun authenticationFailureIsTerminalForOneRendererSession() {
        val gate = RendererLifecycleGate()
        assertTrue(gate.begin())
        assertTrue(gate.markFailed())
        assertFalse(gate.begin())
        assertFalse(gate.markFailed())
        assertEquals(RendererLifecycleState.FAILED, gate.state)
    }

    @Test fun readyRendererDisposesExactlyOnce() {
        val gate = RendererLifecycleGate()
        assertTrue(gate.begin())
        assertTrue(gate.markReady())
        assertTrue(gate.beginDisposal())
        assertFalse(gate.beginDisposal())
        gate.finishDisposal()
        assertEquals(RendererLifecycleState.DISPOSED, gate.state)
    }

    @Test fun onlyKnownMaps3dAuthenticationFailureIsRecoverable() {
        val known = IllegalStateException("onAuthenticationFailed: Failed to fetch MapConfigs").apply {
            stackTrace = arrayOf(StackTraceElement("com.google.android.gms.maps3d.zzbf", "zzc", "sdk", 4))
        }
        val unrelated = IllegalStateException("onAuthenticationFailed: Failed to fetch MapConfigs")
        assertTrue(Maps3dFailurePolicy.isRecoverableAuthenticationFailure(known))
        assertFalse(Maps3dFailurePolicy.isRecoverableAuthenticationFailure(unrelated))
        assertFalse(Maps3dFailurePolicy.isRecoverableAuthenticationFailure(RuntimeException("other")))
    }
}
