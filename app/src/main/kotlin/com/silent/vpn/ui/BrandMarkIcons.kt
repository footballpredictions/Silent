package com.silent.vpn.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.Icon
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.IconCompat
import androidx.core.graphics.drawable.toBitmap
import com.silent.vpn.R

/**
 * Монохромная заглавная S как в SilentLogo.
 * Drawable — hi-res; размер глифа средний (не edge-to-edge, не мелкий).
 */
object BrandMarkIcons {
    /** Status / notification — чуть меньше, чтобы не обрезало в статус-баре. */
    private const val NOTIF_SCALE = 0.70f
    /** QS tile — ~74% высоты canvas (середина между мелким и огромным). */
    private const val TILE_SCALE = 0.85f
    private const val SIZE_PX = 128

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

    fun icon(context: Context): Icon =
        Icon.createWithResource(context, R.drawable.ic_stat_silent)

    fun tileIcon(context: Context): Icon =
        Icon.createWithResource(context, R.drawable.ic_tile_silent)

    fun iconCompat(context: Context): IconCompat =
        IconCompat.createWithResource(context, R.drawable.ic_stat_silent)

    fun brandBitmap(context: Context, sizePx: Int = 128): Bitmap {
        val px = sizePx.coerceAtLeast(48)
        val dr = ContextCompat.getDrawable(context, R.drawable.ic_brand_s)
        if (dr != null) return dr.toBitmap(px, px, Bitmap.Config.ARGB_8888)
        return render(0.72f)
    }
}
