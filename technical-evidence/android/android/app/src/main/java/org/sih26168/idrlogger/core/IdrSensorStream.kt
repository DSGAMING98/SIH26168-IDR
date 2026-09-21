package org.sih26168.idrlogger.core

import org.sih26168.idrlogger.model.LiveIdrSample

fun interface IdrSampleObserver {
    fun onSample(sample: LiveIdrSample)
}

interface IdrSensorStream {
    fun start()
    fun stop()
    fun addObserver(observer: IdrSampleObserver)
    fun removeObserver(observer: IdrSampleObserver)
}
