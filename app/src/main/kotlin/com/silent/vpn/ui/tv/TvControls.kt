package com.silent.vpn.ui.tv

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonColors
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import com.silent.vpn.util.rememberIsTv

@Composable
fun TvTextButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    requestFocusOnOpen: Boolean = false,
    requestFocusKey: Any? = Unit,
    blockFocusUp: Boolean = requestFocusOnOpen,
    contentPadding: PaddingValues = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
    content: @Composable () -> Unit,
) {
    if (!rememberIsTv()) {
        TextButton(
            onClick = onClick,
            modifier = modifier,
            enabled = enabled,
            contentPadding = contentPadding,
            content = { content() },
        )
        return
    }
    val focusMod = if (requestFocusOnOpen) {
        Modifier.tvRequestFocusOnOpen(requestKey = requestFocusKey)
    } else {
        Modifier
    }
    val upMod = if (blockFocusUp) Modifier.tvConsumeFocusUp() else Modifier
    Box(
        modifier = modifier
            .then(focusMod)
            .then(upMod)
            .defaultMinSize(minHeight = 36.dp)
            .tvClickable(enabled = enabled, cornerRadius = 8.dp, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.padding(contentPadding)) { content() }
    }
}

@Composable
fun TvIconButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    requestFocusOnOpen: Boolean = false,
    requestFocusKey: Any? = Unit,
    blockFocusUp: Boolean = false,
    content: @Composable () -> Unit,
) {
    if (!rememberIsTv()) {
        IconButton(onClick = onClick, modifier = modifier, enabled = enabled, content = content)
        return
    }
    val focusMod = if (requestFocusOnOpen) {
        Modifier.tvRequestFocusOnOpen(requestKey = requestFocusKey)
    } else {
        Modifier
    }
    val upMod = if (blockFocusUp) Modifier.tvConsumeFocusUp() else Modifier
    Box(
        modifier = modifier
            .then(focusMod)
            .then(upMod)
            .defaultMinSize(minWidth = 44.dp, minHeight = 44.dp)
            .tvClickable(enabled = enabled, cornerRadius = 10.dp, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

@Composable
fun TvPrimaryButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    shape: Shape = ButtonDefaults.shape,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
    content: @Composable RowScope.() -> Unit,
) {
    if (!rememberIsTv()) {
        Button(
            onClick = onClick,
            modifier = modifier,
            enabled = enabled,
            shape = shape,
            colors = colors,
            content = content,
        )
        return
    }
    val bg = if (enabled) colors.containerColor else colors.disabledContainerColor
    val fg = if (enabled) colors.contentColor else colors.disabledContentColor
    Box(
        modifier = modifier
            .defaultMinSize(minHeight = 48.dp)
            .tvClickable(enabled = enabled, cornerRadius = 12.dp, ringOnly = true, onClick = onClick)
            .background(bg, shape),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CompositionLocalProvider(LocalContentColor provides fg) {
                content()
            }
        }
    }
}
