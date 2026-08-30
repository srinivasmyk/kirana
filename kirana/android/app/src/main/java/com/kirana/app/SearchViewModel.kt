package com.kirana.app

import android.annotation.SuppressLint
import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.kirana.app.net.Api
import com.kirana.app.net.ProductRow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import java.io.IOException

data class UiState(
    val query: String = "",
    val loading: Boolean = false,
    val products: List<ProductRow> = emptyList(),
    val degradedStores: List<String> = emptyList(),
    val error: String? = null,
    val hasSearched: Boolean = false,
    val locationLabel: String? = null,
    val sortByUnitPrice: Boolean = false,
)

class SearchViewModel(app: Application) : AndroidViewModel(app) {

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private val fused = LocationServices.getFusedLocationProviderClient(app)

    // Hyderabad city centre. Only used if location is denied or unavailable —
    // prices will be for the wrong dark store, so the UI says so.
    private var lat = 17.3850
    private var lon = 78.4867
    private var haveRealLocation = false

    fun onQueryChange(q: String) {
        _state.value = _state.value.copy(query = q)
    }

    fun toggleSort() {
        val byUnit = !_state.value.sortByUnitPrice
        _state.value = _state.value.copy(
            sortByUnitPrice = byUnit,
            products = sortRows(_state.value.products, byUnit),
        )
    }

    private fun sortRows(rows: List<ProductRow>, byUnit: Boolean): List<ProductRow> =
        if (byUnit) {
            rows.sortedBy { r -> r.offers.mapNotNull { it.pricePer100 }.minOrNull() ?: Double.MAX_VALUE }
        } else {
            rows.sortedWith(compareByDescending<ProductRow> { it.storesAvailable }
                .thenByDescending { it.maxSaving }
                .thenBy { it.bestPrice })
        }

    /** Called from the permission callback. Keeps coroutine handling in the VM. */
    fun onLocationPermissionResult(granted: Boolean) {
        viewModelScope.launch { refreshLocation(granted) }
    }

    @SuppressLint("MissingPermission")
    private suspend fun refreshLocation(granted: Boolean) {
        if (!granted) {
            _state.value = _state.value.copy(
                locationLabel = "Using Hyderabad centre — grant location for accurate prices"
            )
            return
        }
        runCatching {
            fused.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, null).await()
        }.getOrNull()?.let {
            lat = it.latitude
            lon = it.longitude
            haveRealLocation = true
            _state.value = _state.value.copy(
                locationLabel = "Prices near %.3f, %.3f".format(lat, lon)
            )
        } ?: run {
            _state.value = _state.value.copy(
                locationLabel = "Couldn't get a fix — showing Hyderabad centre"
            )
        }
    }

    fun search() {
        val q = _state.value.query.trim()
        if (q.length < 2) return

        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            try {
                val resp = Api.service.search(q, lat, lon)
                _state.value = _state.value.copy(
                    loading = false,
                    hasSearched = true,
                    products = sortRows(resp.products, _state.value.sortByUnitPrice),
                    degradedStores = resp.storesDegraded,
                    error = null,
                )
            } catch (e: IOException) {
                // By far the most common failure: backend not running, or the
                // phone isn't on the tailnet. Say so plainly.
                _state.value = _state.value.copy(
                    loading = false,
                    hasSearched = true,
                    error = "Can't reach the backend. Check it's running and that " +
                        "this phone is on the same network or Tailscale.",
                )
            } catch (e: Exception) {
                val msg = if (e.message?.contains("401") == true)
                    "API key rejected. BASE_URL/API_KEY in build.gradle.kts must " +
                        "match the backend's .env."
                else "Something went wrong: ${e.message}"
                _state.value = _state.value.copy(loading = false, hasSearched = true, error = msg)
            }
        }
    }
}
