package com.kirana.app.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.kirana.app.UiState
import com.kirana.app.net.Offer
import com.kirana.app.net.ProductRow
import kotlin.math.roundToInt

private fun rupees(v: Double): String =
    if (v == v.roundToInt().toDouble()) "₹${v.roundToInt()}" else "₹%.2f".format(v)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    state: UiState,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onToggleSort: () -> Unit,
) {
    val keyboard = LocalSoftwareKeyboardController.current

    Scaffold(
        topBar = {
            Column {
                TopAppBar(title = { Text("Kirana", fontWeight = FontWeight.Bold) })
                state.locationLabel?.let {
                    Text(
                        it,
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 16.dp, bottom = 6.dp)
                    )
                }
            }
        }
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {

            OutlinedTextField(
                value = state.query,
                onValueChange = onQueryChange,
                placeholder = { Text("Search — try \"amul milk\"") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = {
                    keyboard?.hide(); onSearch()
                }),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)
            )

            if (state.products.isNotEmpty()) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "${state.products.size} results",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(Modifier.weight(1f))
                    FilterChip(
                        selected = state.sortByUnitPrice,
                        onClick = onToggleSort,
                        label = { Text("Best value", fontSize = 12.sp) }
                    )
                }
            }

            // A store being down is worth surfacing — otherwise a missing
            // cheaper option looks like the app is just wrong.
            if (state.degradedStores.isNotEmpty()) {
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)
                        .clip(RoundedCornerShape(8.dp))
                ) {
                    Text(
                        "No results from ${state.degradedStores.joinToString()} — " +
                            "prices below may not be the whole picture.",
                        fontSize = 12.sp,
                        modifier = Modifier.padding(10.dp)
                    )
                }
            }

            when {
                state.loading -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                    CircularProgressIndicator()
                }

                state.error != null -> Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
                    Text(state.error, color = MaterialTheme.colorScheme.error)
                }

                state.hasSearched && state.products.isEmpty() -> Box(
                    Modifier.fillMaxSize().padding(32.dp), Alignment.Center
                ) { Text("Nothing found. Try a shorter or more common term.") }

                else -> LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    items(state.products) { ProductCard(it) }
                }
            }
        }
    }
}

@Composable
private fun ProductCard(row: ProductRow) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {

            Row(verticalAlignment = Alignment.CenterVertically) {
                row.imageUrl?.let {
                    AsyncImage(
                        model = it, contentDescription = null,
                        modifier = Modifier.size(52.dp).clip(RoundedCornerShape(8.dp))
                    )
                    Spacer(Modifier.width(12.dp))
                }
                Column(Modifier.weight(1f)) {
                    Text(
                        row.displayName,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 15.sp,
                        maxLines = 2
                    )
                    row.quantityLabel?.let {
                        Text(it, fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }

            // The headline number. If two stores differ by ₹0 there's nothing
            // to say, so only show a saving when there is one.
            if (row.maxSaving > 0) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "Save ${rupees(row.maxSaving)} by buying from ${row.offers.first().storeName}",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.primary
                )
            }

            Spacer(Modifier.height(10.dp))
            HorizontalDivider()

            row.offers.forEachIndexed { i, offer ->
                OfferRow(offer, isBest = i == 0 && offer.inStock)
            }
        }
    }
}

@Composable
private fun OfferRow(offer: Offer, isBest: Boolean) {
    val context = LocalContext.current
    val enabled = offer.deeplink != null

    Row(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = enabled) {
                offer.deeplink?.let {
                    // Deep-link out to the real store app. Kirana never handles
                    // a cart, a login, or a payment.
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it)))
                }
            }
            .background(
                if (isBest) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f)
                else androidx.compose.ui.graphics.Color.Transparent
            )
            .padding(vertical = 9.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                offer.storeName,
                fontSize = 14.sp,
                fontWeight = if (isBest) FontWeight.Bold else FontWeight.Normal
            )
            offer.pricePer100?.let { pp ->
                val unit = when (offer.baseUnit) {
                    "pc" -> "each"; "g" -> "per 100g"; "ml" -> "per 100ml"; else -> ""
                }
                Text("${rupees(pp)} $unit", fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        if (!offer.inStock) {
            Text("Out of stock", fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            Column(horizontalAlignment = Alignment.End) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    offer.mrp?.let {
                        Text(
                            rupees(it), fontSize = 11.sp,
                            textDecoration = TextDecoration.LineThrough,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(Modifier.width(6.dp))
                    }
                    Text(
                        rupees(offer.price),
                        fontSize = 16.sp,
                        fontWeight = if (isBest) FontWeight.Bold else FontWeight.Medium,
                        color = if (isBest) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurface
                    )
                }
                offer.discountPct?.takeIf { it > 0 }?.let {
                    Text("$it% off", fontSize = 10.sp,
                        color = MaterialTheme.colorScheme.tertiary)
                }
            }
        }
    }
}
