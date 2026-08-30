package com.kirana.app.net

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SearchResponse(
    val query: String,
    val products: List<ProductRow>,
    @Json(name = "stores_queried") val storesQueried: List<String> = emptyList(),
    @Json(name = "stores_degraded") val storesDegraded: List<String> = emptyList(),
    @Json(name = "took_ms") val tookMs: Int = 0,
)

@JsonClass(generateAdapter = true)
data class ProductRow(
    @Json(name = "display_name") val displayName: String,
    val brand: String? = null,
    @Json(name = "quantity_label") val quantityLabel: String? = null,
    @Json(name = "image_url") val imageUrl: String? = null,
    val offers: List<Offer>,
    @Json(name = "best_price") val bestPrice: Double,
    @Json(name = "best_store") val bestStore: String,
    @Json(name = "max_saving") val maxSaving: Double = 0.0,
    @Json(name = "stores_available") val storesAvailable: Int = 0,
)

@JsonClass(generateAdapter = true)
data class Offer(
    val store: String,
    @Json(name = "store_name") val storeName: String,
    val title: String,
    val price: Double,
    val mrp: Double? = null,
    @Json(name = "discount_pct") val discountPct: Int? = null,
    @Json(name = "in_stock") val inStock: Boolean = true,
    val deeplink: String? = null,
    @Json(name = "price_per_100") val pricePer100: Double? = null,
    @Json(name = "base_unit") val baseUnit: String? = null,
)
