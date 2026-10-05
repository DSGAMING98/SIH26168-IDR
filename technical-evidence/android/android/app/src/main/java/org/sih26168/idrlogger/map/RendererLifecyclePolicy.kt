package org.sih26168.idrlogger.map

enum class RendererLifecycleState { UNINITIALIZED, INITIALIZING, READY, FAILED, DISPOSING, DISPOSED }

/** Single-shot renderer session gate. Failure is terminal until a new Activity owns a new gate. */
class RendererLifecycleGate {
    @Volatile var state = RendererLifecycleState.UNINITIALIZED
        private set

    @Synchronized fun begin(): Boolean {
        if (state != RendererLifecycleState.UNINITIALIZED) return false
        state = RendererLifecycleState.INITIALIZING
        return true
    }

    @Synchronized fun markReady(): Boolean {
        if (state != RendererLifecycleState.INITIALIZING) return false
        state = RendererLifecycleState.READY
        return true
    }

    @Synchronized fun markFailed(): Boolean {
        if (state != RendererLifecycleState.INITIALIZING && state != RendererLifecycleState.READY) return false
        state = RendererLifecycleState.FAILED
        return true
    }

    @Synchronized fun beginDisposal(): Boolean {
        if (state == RendererLifecycleState.DISPOSING || state == RendererLifecycleState.DISPOSED) return false
        state = RendererLifecycleState.DISPOSING
        return true
    }

    @Synchronized fun finishDisposal() {
        check(state == RendererLifecycleState.DISPOSING)
        state = RendererLifecycleState.DISPOSED
    }
}

/**
 * Identifies the 0.2.2 SDK defect where an authentication rejection escapes its private worker
 * thread instead of reaching OnMap3DViewReadyCallback.onError. All other failures remain fatal.
 */
object Maps3dFailurePolicy {
    fun isRecoverableAuthenticationFailure(error: Throwable): Boolean =
        error is IllegalStateException &&
            error.message == "onAuthenticationFailed: Failed to fetch MapConfigs" &&
            error.stackTrace.any { it.className.startsWith("com.google.android.gms.maps3d.") }
}
