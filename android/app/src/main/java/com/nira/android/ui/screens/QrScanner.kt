package com.nira.android.ui.screens

import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors

private const val TAG = "NiraQrScanner"

/**
 * Camera preview that reports the first QR code it reads.
 *
 * [onScanned] fires once and then stops: a scanner that keeps firing would
 * redeem the same single-use pairing token several times, and every attempt
 * after the first is refused — which would look to the user like a failure
 * rather than the success it actually was.
 */
@Composable
fun QrScanner(onScanned: (String) -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }
    val previewView = remember { PreviewView(context) }
    val delivered = remember { java.util.concurrent.atomic.AtomicBoolean(false) }

    DisposableEffect(Unit) {
        val providerFuture = ProcessCameraProvider.getInstance(context)
        providerFuture.addListener({
            val provider = runCatching { providerFuture.get() }.getOrNull()
                ?: return@addListener

            val preview = Preview.Builder().build().also {
                it.surfaceProvider = previewView.surfaceProvider
            }

            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also { useCase ->
                    useCase.setAnalyzer(executor) { proxy ->
                        val image = proxy.image
                        if (image == null || delivered.get()) {
                            proxy.close()
                            return@setAnalyzer
                        }
                        val input = InputImage.fromMediaImage(
                            image, proxy.imageInfo.rotationDegrees
                        )
                        scanner.process(input)
                            .addOnSuccessListener { codes ->
                                val value = codes.firstOrNull {
                                    it.format == Barcode.FORMAT_QR_CODE
                                }?.rawValue
                                if (value != null && delivered.compareAndSet(false, true)) {
                                    ContextCompat.getMainExecutor(context).execute {
                                        onScanned(value)
                                    }
                                }
                            }
                            .addOnFailureListener { Log.d(TAG, "scan failed", it) }
                            .addOnCompleteListener { proxy.close() }
                    }
                }

            runCatching {
                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis
                )
            }.onFailure { Log.w(TAG, "could not start camera", it) }
        }, ContextCompat.getMainExecutor(context))

        onDispose {
            runCatching { ProcessCameraProvider.getInstance(context).get().unbindAll() }
            scanner.close()
            executor.shutdown()
        }
    }

    AndroidView(factory = { previewView }, modifier = modifier)
}
