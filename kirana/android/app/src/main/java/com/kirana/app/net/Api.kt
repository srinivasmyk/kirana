package com.kirana.app.net

import com.kirana.app.BuildConfig
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.GET
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

interface KiranaApi {
    @GET("search")
    suspend fun search(
        @Query("q") query: String,
        @Query("lat") lat: Double,
        @Query("lon") lon: Double,
    ): SearchResponse
}

object Api {
    val service: KiranaApi by lazy {
        val client = OkHttpClient.Builder()
            // The backend fans out to four stores, so a cold search can take a
            // few seconds. Don't set the read timeout tight.
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                chain.proceed(
                    chain.request().newBuilder()
                        .addHeader("X-API-Key", BuildConfig.API_KEY)
                        .build()
                )
            }
            .build()

        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

        Retrofit.Builder()
            .baseUrl(BuildConfig.BASE_URL)
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(KiranaApi::class.java)
    }
}
