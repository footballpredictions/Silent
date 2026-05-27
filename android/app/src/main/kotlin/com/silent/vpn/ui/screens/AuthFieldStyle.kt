package com.silent.vpn.ui.screens

import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.TextFieldColors
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object AuthColors {
    val screenBg = Color(0xFF0A0A0A)
    val fieldBg = Color(0xFF161616)
    val fieldText = Color.White
    val fieldPlaceholder = Color(0xFF9CA3AF)
    val label = Color(0xFFD1D5DB)
    val hint = Color(0xFF9CA3AF)
    val border = Color(0xFF374151)
    val borderFocused = Color(0xFFE5E7EB)
    val tabBg = Color(0xFF1F1F1F)
    val divider = Color(0xFF2A2A2A)
}

@Composable
fun authTextFieldColors(): TextFieldColors = OutlinedTextFieldDefaults.colors(
    focusedTextColor = AuthColors.fieldText,
    unfocusedTextColor = AuthColors.fieldText,
    disabledTextColor = AuthColors.fieldText.copy(alpha = 0.5f),
    cursorColor = AuthColors.fieldText,
    focusedContainerColor = AuthColors.fieldBg,
    unfocusedContainerColor = AuthColors.fieldBg,
    disabledContainerColor = AuthColors.fieldBg,
    focusedBorderColor = AuthColors.borderFocused,
    unfocusedBorderColor = AuthColors.border,
    focusedPlaceholderColor = AuthColors.fieldPlaceholder,
    unfocusedPlaceholderColor = AuthColors.fieldPlaceholder,
)
