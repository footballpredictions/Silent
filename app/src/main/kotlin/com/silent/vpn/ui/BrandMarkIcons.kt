package com.silent.vpn.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.Icon
import android.util.DisplayMetrics
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.IconCompat
import androidx.core.graphics.drawable.toBitmap
import com.silent.vpn.R

/**
 * Монохромная заглавная S как в SilentLogo.
 * На TV/4K — крупный bitmap (≥512px) и hi-res drawable, иначе пиксели при апскейле.
 */
object BrandMarkIcons {
    private const val NOTIF_SCALE = 0.70f
    private const val TILE_SCALE = 0.92f
    private const val MIN_SIZE_PX = 512

    @Volatile private var cachedNotif: Bitmap? = null
    @Volatile private var cachedTile: Bitmap? = null
    @Volatile private var cachedSize: Int = 0

    private fun targetSizePx(metrics: DisplayMetrics?): Int {
        val density = metrics?.density?.takeIf { it > 0f } ?: 2f
        return (24f * density * 8f).toInt().coerceAtLeast(MIN_SIZE_PX)
    }

    private fun render(size: Int, scale: Float): Bitmap {
        val bmp = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG or Paint.LINEAR_TEXT_FLAG).apply {
            color = Color.WHITE
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            textAlign = Paint.Align.CENTER
            textSize = size * scale
            isFilterBitmap = true
            hinting = Paint.HINTING_ON
        }
        val fm = paint.fontMetrics
        val y = size / 2f - (fm.ascent + fm.descent) / 2f
        canvas.drawText("S", size / 2f, y, paint)
        return bmp
    }

    private fun ensureCache(metrics: DisplayMetrics?) {
        val size = targetSizePx(metrics)
        if (cachedSize == size &&
            cachedNotif?.isRecycled == false &&
            cachedTile?.isRecycled == false
        ) {
            return
        }
        cachedNotif?.takeIf { !it.isRecycled }?.recycle()
        cachedTile?.takeIf { !it.isRecycled }?.recycle()
        cachedNotif = render(size, NOTIF_SCALE)
        cachedTile = render(size, TILE_SCALE)
        cachedSize = size
    }

    fun bitmap(context: Context? = null): Bitmap {
        ensureCache(context?.resources?.displayMetrics)
        return cachedNotif!!
    }

    fun tileBitmap(context: Context? = null): Bitmap {
        ensureCache(context?.resources?.displayMetrics)
        return cachedTile!!
    }

    fun icon(context: Context): Icon =
        Icon.createWithResource(context, R.drawable.ic_stat_silent)

    fun tileIcon(context: Context): Icon =
        Icon.createWithResource(context, R.drawable.ic_tile_silent)

    fun iconCompat(context: Context): IconCompat =
        IconCompat.createWithResource(context, R.drawable.ic_stat_silent)

    fun brandBitmap(context: Context, sizePx: Int = 512): Bitmap {
        val px = sizePx.coerceAtLeast(MIN_SIZE_PX)
        val dr = ContextCompat.getDrawable(context, R.drawable.ic_brand_s)
        if (dr != null) return dr.toBitmap(px, px, Bitmap.Config.ARGB_8888)
        val bmp = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888)
        Canvas(bmp).drawColor(Color.BLACK)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            textAlign = Paint.Align.CENTER
            textSize = px * 0.72f
        }
        val fm = paint.fontMetrics
        Canvas(bmp).drawText("S", px / 2f, px / 2f - (fm.ascent + fm.descent) / 2f, paint)
        return bmp
    }
}
