package org.sih26168.idrlogger.engine

import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.model.*

class ExternalSensorAdapterTest {
    private fun imu(t: Long) = InertialInput(t, Vector3(0.0,0.0,9.80665), Vector3(0.0,0.0,0.0),
        Vector3(20.0,30.0,10.0), Vector3(0.0,0.0,9.80665), Quaternion(0.0,0.0,0.0,1.0))

    @Test fun twoHundredHzInputKeepsTenHzModelCadence() {
        val samples = mutableListOf<LiveIdrSample>()
        val adapter = ExternalSensorAdapter { samples.add(it); NavigationState() }
        repeat(200) { adapter.accept(imu(1_000_000_000L+it*5_000_000L)) }
        assertEquals(10,samples.size)
        assertTrue(samples.zipWithNext().all { (a,b) -> b.monotonicTimestampNs-a.monotonicTimestampNs==100_000_000L })
    }

    @Test fun blackoutRemovesSeparatelySuppliedGnss() {
        var sample: LiveIdrSample? = null
        val adapter = ExternalSensorAdapter { sample=it; NavigationState() }
        val fix = EngineTestFixtures.sample(0,1_000_000_000L,gnssEastM=0.0).gnss!!
        adapter.accept(imu(1_000_000_000L),ExternalGnssInput(1_000_000_000L,fix),blackout=true)
        assertNull(sample!!.gnss)
        assertFalse(sample!!.gnssIsFresh)
    }

    @Test(expected=IllegalArgumentException::class) fun rejectsFutureGnss() {
        val fix = EngineTestFixtures.sample(0,1_000_000_000L,gnssEastM=0.0).gnss!!
        ExternalSensorAdapter { NavigationState() }.accept(imu(1_000_000_000L),ExternalGnssInput(2_000_000_000L,fix))
    }

    @Test(expected=IllegalArgumentException::class) fun rejectsRepeatedTimestamp() {
        val adapter = ExternalSensorAdapter { NavigationState() }
        adapter.accept(imu(1_000_000_000L)); adapter.accept(imu(1_000_000_000L))
    }

    @Test fun missingAttitudeIsNotFabricated() {
        var sample: LiveIdrSample? = null
        ExternalSensorAdapter { sample=it; NavigationState() }.accept(imu(1_000_000_000L).copy(gravityMps2=null,deviceToEnu=null))
        assertNull(sample!!.rotation); assertNull(sample!!.gravity)
        assertFalse(sample!!.availability.rotationVector)
    }

    @Test fun androidAdapterPreservesExactInput() {
        val original = EngineTestFixtures.sample(0,1_000_000_000L,blackout=true)
        AndroidNavigationAdapter { assertSame(original,it); NavigationState() }.accept(original)
    }

    @Test fun benchmarkSyntheticTwoHundredHzReplay() {
        val engine=IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        val adapter=ExternalSensorAdapter(engine::process)
        val timings=DoubleArray(20_000)
        var emitted=0
        for (i in timings.indices) {
            val frame=imu(1_600_000_000L+i*5_000_000L)
            val begin=System.nanoTime()
            if (adapter.accept(frame,blackout=true)!=null) emitted++
            timings[i]=(System.nanoTime()-begin)/1e6
        }
        val sorted=timings.sorted()
        println("EXTERNAL_SYNTHETIC_HOST input_hz=200 engine_hz=10 inputs=${timings.size} outputs=$emitted mean_ms=${timings.average()} p95_ms=${sorted[19000]} throughput=${1000/timings.average()}")
        assertEquals(1000,emitted)
        assertTrue(timings.average()<5.0)
    }
}
