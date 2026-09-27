package com.silent.vpn.policy

/** Кнопка и жест «назад»: на уровень меню назад. С главного экрана — обычный выход в фон. */
enum class MenuBackStep {
    CLOSE_DEBUG_LOG,
    TO_MENU_ROOT,
    CLOSE_MENU,
    LEAVE_APP,
}

object MenuBackPolicy {
    fun step(debugLogOpen: Boolean, menuOpen: Boolean, onMenuRoot: Boolean): MenuBackStep = when {
        debugLogOpen -> MenuBackStep.CLOSE_DEBUG_LOG
        menuOpen && !onMenuRoot -> MenuBackStep.TO_MENU_ROOT
        menuOpen -> MenuBackStep.CLOSE_MENU
        else -> MenuBackStep.LEAVE_APP
    }
}
