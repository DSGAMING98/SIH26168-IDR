package org.sih26168.idrlogger.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import org.sih26168.idrlogger.engine.MlRuntimeState
import org.sih26168.idrlogger.engine.LocalizationMode

class UiSemanticsTest {
    @Test fun mapsInternalMlStatesToHonestHumanLabels() {
        assertEquals("ML ASSIST ACTIVE", UiSemantics.aiLabel(MlRuntimeState.ML_ACCEPTED))
        assertEquals("ML ASSIST GATED", UiSemantics.aiLabel(MlRuntimeState.ML_OOD_LIMITED))
        assertEquals("ML ASSIST OOD BLOCKED", UiSemantics.aiLabel(MlRuntimeState.ML_REJECTED))
        assertEquals("ML ASSIST UNAVAILABLE", UiSemantics.aiLabel(MlRuntimeState.ML_UNAVAILABLE))
        assertEquals("ML ASSIST WARMING", UiSemantics.aiLabel(MlRuntimeState.ML_WARMING))
    }

    @Test fun topLevelAndDiagnosticsShareTheSameLocalizationVocabulary() {
        LocalizationMode.entries.forEach { state ->
            assertEquals(UiSemantics.localizationLabel(state), UiSemantics.localizationLabel(state))
        }
        assertEquals("IDR ACTIVE", UiSemantics.localizationLabel(LocalizationMode.IDR_ACTIVE))
        assertEquals("CALIBRATION REQUIRED", UiSemantics.localizationLabel(LocalizationMode.CALIBRATION_REQUIRED))
    }
}
