/** Кнопки свернуть / полностью закрыть (окно + трей). */
export default function WindowControls() {
  const api = (window as any).electronAPI
  return (
    <div className="flex items-center gap-1.5 pl-1 shrink-0">
      <button
        type="button"
        onClick={() => api?.minimize?.()}
        title="Свернуть"
        aria-label="Свернуть"
        className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-gray-400 transition-colors"
      />
      <button
        type="button"
        onClick={() => api?.quitApp?.()}
        title="Закрыть"
        aria-label="Закрыть приложение"
        className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-red-400 transition-colors"
      />
    </div>
  )
}
