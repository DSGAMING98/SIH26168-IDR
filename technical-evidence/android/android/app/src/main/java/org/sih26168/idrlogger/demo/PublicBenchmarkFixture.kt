package org.sih26168.idrlogger.demo

import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.TrajectoryPoint

data class PublicBenchmarkMetrics(
    val scenarioId: String,
    val durationSeconds: Double,
    val referenceDistanceM: Double,
    val rawFinalErrorM: Double,
    val intelligentFinalErrorM: Double,
    val intelligentDriftPercent: Double,
)

data class PublicBenchmarkReplay(
    val reference: List<TrajectoryPoint>,
    val rawDr: List<TrajectoryPoint>,
    val intelligentIdr: List<TrajectoryPoint>,
    val metrics: PublicBenchmarkMetrics,
)

/**
 * Evaluator-only, 2-second-downsampled public IO-VNBD S1_60_STOP_GO replay.
 * These tracks are presentation data and are never passed to [org.sih26168.idrlogger.engine.IdrEngine].
 */
object PublicBenchmarkFixture {
    val replay: PublicBenchmarkReplay by lazy {
        val rows = listOf(
            row(0.0, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000),
            row(2.0, 7.428, -27.821, 2.999, -20.080, 10.024, -19.384),
            row(4.0, 15.216, -55.053, 3.298, -39.491, 20.789, -40.206),
            row(6.0, 22.718, -82.173, 1.528, -58.836, 30.553, -61.241),
            row(8.0, 30.418, -108.571, 1.041, -77.259, 38.166, -82.946),
            row(10.0, 37.785, -135.113, 0.280, -95.028, 44.727, -103.138),
            row(12.0, 44.955, -159.798, -0.850, -112.613, 51.415, -122.943),
            row(14.0, 51.745, -183.283, -2.425, -130.330, 56.635, -140.549),
            row(16.0, 57.776, -204.377, -3.219, -147.341, 60.937, -158.020),
            row(18.0, 62.613, -220.911, -3.321, -162.794, 66.302, -176.770),
            row(20.0, 65.821, -232.242, -2.014, -177.063, 72.191, -193.113),
            row(22.0, 67.293, -237.379, 0.395, -189.705, 74.142, -198.106),
            row(24.0, 67.354, -237.880, 2.583, -201.715, 73.948, -197.323),
            row(26.0, 67.795, -239.570, 1.889, -215.271, 75.484, -202.034),
            row(28.0, 69.471, -245.608, -2.244, -230.645, 79.658, -215.462),
            row(30.0, 70.482, -249.422, -7.138, -245.936, 79.496, -216.003),
            row(32.0, 71.024, -251.345, -12.752, -261.130, 79.078, -215.358),
            row(34.0, 71.072, -251.601, -18.947, -276.129, 78.409, -213.772),
            row(36.0, 71.058, -251.735, -26.249, -291.509, 67.879, -178.851),
            row(38.0, 71.031, -251.846, -34.515, -307.282, 67.872, -178.827),
            row(40.0, 71.004, -251.946, -43.656, -323.279, 67.865, -178.797),
            row(42.0, 70.963, -252.046, -53.591, -339.445, 67.857, -178.769),
            row(44.0, 70.929, -252.135, -64.260, -355.750, 67.850, -178.735),
            row(46.0, 70.895, -252.179, -75.482, -372.088, 67.841, -178.695),
            row(48.0, 70.855, -252.224, -86.976, -388.388, 67.831, -178.653),
            row(50.0, 70.814, -252.279, -98.862, -404.625, 67.823, -178.613),
            row(52.0, 70.780, -252.324, -110.995, -420.772, 67.813, -178.565),
            row(54.0, 70.739, -252.368, -123.327, -436.794, 67.805, -178.523),
            row(56.0, 70.705, -252.402, -135.951, -452.710, 67.796, -178.479),
            row(58.0, 70.665, -252.457, -148.844, -468.502, 67.788, -178.433),
            row(59.9, 70.644, -252.524, -161.245, -483.343, 67.780, -178.387),
        )
        PublicBenchmarkReplay(
            reference = rows.map { TrajectoryPoint(it.referenceE, it.referenceN, LocalizationMode.GNSS_ACTIVE) },
            rawDr = rows.map { TrajectoryPoint(it.rawE, it.rawN, LocalizationMode.IDR_ACTIVE) },
            intelligentIdr = rows.map { TrajectoryPoint(it.idrE, it.idrN, LocalizationMode.IDR_ACTIVE) },
            metrics = PublicBenchmarkMetrics("S1_60_STOP_GO", 60.0, 262.7939441749739, 327.1854981423306, 74.19228462027947, 28.23211351129181),
        )
    }

    private data class Row(val t: Double, val referenceE: Double, val referenceN: Double, val rawE: Double, val rawN: Double, val idrE: Double, val idrN: Double)
    private fun row(t: Double, referenceE: Double, referenceN: Double, rawE: Double, rawN: Double, idrE: Double, idrN: Double) = Row(t, referenceE, referenceN, rawE, rawN, idrE, idrN)
}
