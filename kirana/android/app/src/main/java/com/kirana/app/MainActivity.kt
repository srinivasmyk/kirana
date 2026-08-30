package com.kirana.app

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kirana.app.ui.SearchScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface { App() }
            }
        }
    }
}

@Composable
private fun App(vm: SearchViewModel = viewModel()) {
    val state by vm.state.collectAsState()

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> vm.onLocationPermissionResult(granted) }

    LaunchedEffect(Unit) { launcher.launch(Manifest.permission.ACCESS_COARSE_LOCATION) }

    SearchScreen(
        state = state,
        onQueryChange = vm::onQueryChange,
        onSearch = vm::search,
        onToggleSort = vm::toggleSort,
    )
}
