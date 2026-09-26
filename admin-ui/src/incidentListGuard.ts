/** Поколение списка инцидентов: ответ опроса, начатый до очистки, не возвращает строки на экран. */

export function bumpIncidentGen(gen: number): number {
  return gen + 1
}

export function shouldApplyIncidentList(startedGen: number, currentGen: number): boolean {
  return startedGen === currentGen
}
