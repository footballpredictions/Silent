package com.silent.vpn.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.Icon
import androidx.core.graphics.drawable.IconCompat

/**
 * Монохромная заглавная S как в [com.silent.vpn.ui.components.SilentLogo]:
 * системный [Typeface.DEFAULT] + Bold (на стоке — Roboto Bold).
 * Для status bar / notification / QS tile — без квадрата фона.
 */
object BrandMarkIcons {
    private const val SIZE_PX = 128
    /** Status / notification — чуть меньше, чтобы не обрезало в статус-баре. */
    private const val NOTIF_SCALE = 0.70f
    /** QS tile — крупнее: система сильно уменьшает иконку в плитке. */
    private const val TILE_SCALE = 0.92f

    @Volatile
    private var cachedNotif: Bitmap? = null

    @Volatile
    private var cachedTile: Bitmap? = null

    private fun render(scale: Float): Bitmap {
        val size = SIZE_PX
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG).apply {
            color = Color.WHITE
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            textAlign = Paint.Align.CENTER
            textSize = size * scale
        }
        val fm = paint.fontMetrics
        val y = size / 2f - (fm.ascent + fm.descent) / 2f
        canvas.drawText("S", size / 2f, y, paint)
        return bmp
    }

    fun bitmap(): Bitmap {
        cachedNotif?.takeIf { !it.isRecycled }?.let { return it }
        return render(NOTIF_SCALE).also { cachedNotif = it }
    }

    fun tileBitmap(): Bitmap {
        cachedTile?.takeIf { !it.isRecycled }?.let { return it }
        return render(TILE_SCALE).also { cachedTile = it }
    }

    fun icon(): Icon = Icon.createWithBitmap(bitmap())

    fun tileIcon(): Icon = Icon.createWithBitmap(tileBitmap())

    fun iconCompat(): IconCompat = IconCompat.createWithBitmap(bitmap())
}
