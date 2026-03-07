/**
 * scriptSplitter.ts
 * Splits a combined Playwright pytest script into one script per test case.
 */

export interface IndividualScript {
  testId: string;    // e.g. "TC_001"
  testName: string;  // extracted from docstring
  script: string;    // header + this function + __main__ block
}

const MAIN_BLOCK =
  '\n\nif __name__ == "__main__":\n' +
  '    import pytest as _pytest, sys as _sys, os as _os\n' +
  '    _args = [__file__, "-v", "--tb=short", "--browser", "chromium"]\n' +
  '    if _os.environ.get("PLAYWRIGHT_HEADLESS", "1") == "0":\n' +
  '        _args.append("--headed")\n' +
  '    _sys.exit(_pytest.main(_args))\n';

/**
 * Splits a combined pytest script string (header + multiple def test_*() functions)
 * into individual runnable scripts — one per test case.
 */
export function splitCombinedScript(combined: string): IndividualScript[] {
  // Find where the first test function starts
  const firstTestIdx = combined.search(/^def test_/m);
  if (firstTestIdx === -1) return [];

  const header = combined.slice(0, firstTestIdx).trimEnd();

  // Split on every "def test_" boundary (look-ahead keeps the delimiter)
  const funcBlocks = combined
    .slice(firstTestIdx)
    .split(/(?=^def test_)/m)
    .filter(Boolean);

  return funcBlocks.map((block) => {
    // Extract function name suffix → use as testId
    const nameMatch = block.match(/^def test_(\w+)\s*\(/m);
    const rawName = nameMatch ? nameMatch[1] : 'UNKNOWN';
    const testId = rawName.toUpperCase();

    // Try to extract a human-readable test name from the docstring
    // Pattern: """  Test ID: TC_001\n  <name>\n  """
    const docMatch = block.match(/"""\s*\n\s*Test ID:\s*\S+\s*\n\s*([\s\S]*?)\s*"""/);
    const testName = docMatch ? docMatch[1].trim() : rawName;

    // Build runnable individual script
    const mainBlock = block.includes('if __name__ == "__main__"') ? '' : MAIN_BLOCK;
    const script = header + '\n\n' + block.trimEnd() + mainBlock;

    return { testId, testName, script };
  });
}
