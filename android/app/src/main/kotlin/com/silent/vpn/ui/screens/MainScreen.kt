package com.silent.vpn.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.ui.theme.parseColor

enum class VpnState { DISCONNECTED, CONNECTING, CONNECTED, DISCONNECTING }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    profile: UserProfile?,
    vpnState: VpnState,
    theme: ThemeData?,
    onToggle: () -> Unit,
    onMenuClick: () -> Unit,
) {
    val bg = parseColor(theme?.background_color ?: "#FFFFFF", Color.White)
    val fg = parseColor(theme?.text_color ?: "#000000", Color.Black)
    val toggleOn = parseColor(theme?.toggle_on_color ?: "#000000", Color.Black)
    val toggleOff = parseColor(theme?.toggle_off_color ?: "#CCCCCC", Color(0xFFCCCCCC))

    val isConnected = vpnState == VpnState.CONNECTED
    val isTransitioning = vpnState == VpnState.CONNECTING || vpnState == VpnState.DISCONNECTING

    // Pulse animation when connected
    val pulseAnim = rememberInfiniteTransition(label = "pulse")
    val pulseScale by pulseAnim.animateFloat(
        initialValue = 1f, targetValue = if (isConnected) 1.15f else 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1500, easing = EaseInOut),
            repeatMode = RepeatMode.Reverse,
        ), label = "scale"
    )

    // Toggle animation
    val toggleOffset by animateFloatAsState(
        targetValue = if (isConnected) 1f else 0f,
        animationSpec = spring(dampingRatio = 0.7f, stiffness = Spring.StiffnessMediumLow),
        label = "toggle"
    )

    Scaffold(
        containerColor = bg,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        theme?.app_name?.uppercase() ?: "SILENT",
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 4.sp,
                        fontSize = 14.sp,
                        color = fg,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onMenuClick) {
                        Icon(Icons.Default.Menu, contentDescription = "Menu", tint = fg)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = bg),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(modifier = Modifier.weight(1f))

            // Status label
            Text(
                text = when (vpnState) {
                    VpnState.CONNECTED -> "Подключено"
                    VpnState.CONNECTING -> "Подключение..."
                    VpnState.DISCONNECTING -> "Отключение..."
                    VpnState.DISCONNECTED -> "Отключено"
                },
                color = when (vpnState) {
                    VpnState.CONNECTED -> Color(0xFF22C55E)
                    VpnState.DISCONNECTED -> fg.copy(alpha = 0.4f)
                    else -> fg.copy(alpha = 0.6f)
                },
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = 1.sp,
            )

            Spacer(modifier = Modifier.height(32.dp))

            // Big toggle with pulse ring
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier.size(160.dp),
            ) {
                if (isConnected) {
                    Box(
                        modifier = Modifier
                            .size(140.dp)
                            .scale(pulseScale)
                            .background(toggleOn.copy(alpha = 0.12f), CircleShape)
                    )
                }

                // Toggle track
                Box(
                    modifier = Modifier
                        .width(130.dp)
                        .height(64.dp)
                        .background(
                            if (isConnected) toggleOn else toggleOff,
                            RoundedCornerShape(32.dp),
                        )
                        .clickable(enabled = !isTransitioning, onClick = onToggle),
                    contentAlignment = Alignment.CenterStart,
                ) {
                    // Thumb
                    val thumbOffset = (130.dp - 64.dp) * toggleOffset
                    Box(
                        modifier = Modifier
                            .padding(start = 4.dp)
                            .offset(x = thumbOffset)
                            .size(56.dp)
                            .background(bg, CircleShape)
                            .border(2.dp, if (isConnected) toggleOn else toggleOff, CircleShape),
                    ) {
                        if (isTransitioning) {
                            CircularProgressIndicator(
                                modifier = Modifier
                                    .size(20.dp)
                                    .align(Alignment.Center),
                                strokeWidth = 2.dp,
                                color = fg,
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.weight(1f))

            // Subscription info at bottom
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 32.dp),
                contentAlignment = Alignment.Center,
            ) {
                if (profile?.subscription?.is_active == true) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "Оплачено",
                            color = Color(0xFF22C55E),
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            "до ${profile.subscription.expires_at?.take(10)?.split("-")?.reversed()?.joinToString(".")}",
                            color = fg.copy(alpha = 0.5f),
                            fontSize = 11.sp,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                } else {
                    Button(
                        onClick = { /* Open subscription screen */ },
                        colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = bg),
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Оформить подписку", fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}
