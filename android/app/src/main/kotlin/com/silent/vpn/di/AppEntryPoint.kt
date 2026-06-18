package com.silent.vpn.di

import com.silent.vpn.data.SilentRepository
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@EntryPoint
@InstallIn(SingletonComponent::class)
interface AppEntryPoint {
    fun silentRepository(): SilentRepository
}
