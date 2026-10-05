package org.sih26168.idrlogger.ui

import org.sih26168.idrlogger.engine.MlRuntimeState

object UiSemantics {
    fun aiLabel(state: MlRuntimeState): String = when (state) {
        MlRuntimeState.ML_ACCEPTED -> "ML ASSIST ACTIVE"
        MlRuntimeState.ML_OOD_LIMITED -> "ML ASSIST GATED"
        MlRuntimeState.ML_REJECTED -> "ML ASSIST OOD BLOCKED"
        MlRuntimeState.ML_UNAVAILABLE -> "ML ASSIST UNAVAILABLE"
        MlRuntimeState.ML_WARMING -> "ML ASSIST WARMING"
    }

    fun localizationLabel(state: org.sih26168.idrlogger.engine.LocalizationMode): String = when (state) {
        org.sih26168.idrlogger.engine.LocalizationMode.WAITING_FOR_GNSS -> "WAITING FOR GNSS"
        org.sih26168.idrlogger.engine.LocalizationMode.CALIBRATING -> "CALIBRATING"
        org.sih26168.idrlogger.engine.LocalizationMode.CALIBRATION_REQUIRED -> "CALIBRATION REQUIRED"
        org.sih26168.idrlogger.engine.LocalizationMode.GNSS_ACTIVE -> "GNSS ACTIVE"
        org.sih26168.idrlogger.engine.LocalizationMode.GNSS_DEGRADED -> "GNSS DEGRADED"
        org.sih26168.idrlogger.engine.LocalizationMode.IDR_ACTIVE -> "IDR ACTIVE"
        org.sih26168.idrlogger.engine.LocalizationMode.GNSS_VERIFYING -> "VERIFYING GNSS"
        org.sih26168.idrlogger.engine.LocalizationMode.GNSS_RECOVERING -> "RECONCILING"
        org.sih26168.idrlogger.engine.LocalizationMode.ERROR -> "ERROR"
    }
}
