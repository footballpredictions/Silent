package com.silent.vpn.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.silent.vpn.ui.theme.UiDimens
import com.silent.vpn.ui.theme.UiFont
import com.silent.vpn.ui.theme.mutedFg
import com.silent.vpn.ui.tv.tvMenuClickable
import com.silent.vpn.util.rememberIsTv

@Composable
fun MenuNavItem(
    label: String,
    fg: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    textColor: Color = fg,
    showChevron: Boolean = true,
) {
    val isTv = rememberIsTv()
    Box(
        modifier = modifier
            .fillMaxWidth()
            .then(
                if (isTv) {
                    Modifier.tvMenuClickable(
                        cornerRadius = 10.dp,
                        onClick = onClick,
                    )
                } else {
                    Modifier.clickable(onClick = onClick)
                },
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = UiDimens.menuItemPaddingH,
                    vertical = UiDimens.menuItemPaddingV,
                ),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                fontSize = UiFont.sm,
                color = textColor,
                modifier = Modifier.weight(1f),
            )
            if (showChevron) {
                Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    tint = mutedFg(fg, 0.3f),
                    modifier = Modifier.size(14.dp),
                )
            }
        }
    }
}

@Composable
fun MenuNavLogout(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isTv = rememberIsTv()
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 8.dp)
            .then(
                if (isTv) {
                    Modifier.tvMenuClickable(
                        cornerRadius = 10.dp,
                        onClick = onClick,
                    )
                } else {
                    Modifier.clickable(
                        onClick = onClick,
                        interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                        indication = null,
                    )
                },
            ),
    ) {
        Text(
            "Выйти",
            fontSize = UiFont.sm,
            color = com.silent.vpn.ui.theme.UiColors.Red500,
            fontWeight = FontWeight.Normal,
            modifier = Modifier.padding(
                horizontal = UiDimens.menuItemPaddingH,
                vertical = UiDimens.menuItemPaddingV,
            ),
        )
    }
}
