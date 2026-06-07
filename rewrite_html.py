import re

file_path = "/Users/hakim/Library/Mobile Documents/com~apple~CloudDocs/DEV/Investment-AI_T_latest/Penting/system running.html"

with open(file_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# 1. Update the Hero paragraph
hero_p_old = r"Dokumen ini menerangkan flow terbaru yang kita rancang.*?emergency\.</p>"
hero_p_new = """Dokumen ini menerangkan flow paling latest: <code>master_analyzer.py</code> berfungsi sebagai otak utama
        yang membaca data dari MT5 (Master Account), menganalisis pasaran XAUUSD menggunakan Cloud AI (OpenRouter)
        pada selang masa berbeza (Scalping 10m, Intraday 30m, Swing 1h), dan menyimpan Signal Trading (Entry Zone, SL, TP) ke Supabase. 
        Sistem kini fokus 100% kepada XAUUSD. Segala signal akan dibaca oleh dashboard dan akan diexecute di akaun terminal client.
      </p>"""
html_content = re.sub(hero_p_old, hero_p_new, html_content, flags=re.DOTALL)

# 2. Update Status Grid
status_grid_old = r'<div class="status-grid">.*?</div>\s*</header>'
status_grid_new = """<div class="status-grid">
        <div class="status">
          <b>Master Analyzer</b>
          <span>Menganalisis XAUUSD pada selang 10m, 30m, dan 1h. Tiada execution, hanya hasilkan Signal.</span>
        </div>
        <div class="status">
          <b>Multi-Timeframe AI</b>
          <span>AI tidak lagi pilih style. Bot memaksa AI menganalisis ikut specific style (Scalping/Intraday/Swing).</span>
        </div>
        <div class="status">
          <b>Cloud Sync</b>
          <span>Supabase menyimpan Signal AI (Entry Zone, TP, SL) menggunakan composite key (symbol, trade_style).</span>
        </div>
        <div class="status">
          <b>Vercel Dashboard</b>
          <span>Memaparkan signal-signal terbaru untuk setiap timeframe secara serentak.</span>
        </div>
      </div>
    </header>"""
html_content = re.sub(status_grid_old, status_grid_new, html_content, flags=re.DOTALL)

# 3. Update Flow Trading Utama Diagram
diagram_old = r'<pre class="diagram"><span class="good">MAIN LOOP \(10m/30m/1h Intervals\).*?</pre>'
diagram_new = """<pre class="diagram"><span class="good">MASTER ANALYZER LOOP (10m / 30m / 1h Intervals)</span>
  |
  v
Get tick price from MT5 (XAUUSD only)
  |
  v
Check timers for Scalping (10m), Intraday (30m), Swing (1h)
  |
  v
For each due style:
  |
  v
Get H4 / H1 / M30 / M15 / M5 / M1 candle data
  |
  v
Calculate indicators + XAUUSD pattern engine
  |
  v
Call Cloud AI with FORCED STYLE (e.g. "Scalping")
  |
  v
AI translates pattern + market context into JSON:
  +-- BUY / SELL / HOLD
  +-- entry_zone
  +-- sl_price
  +-- tp_price
  +-- confidence & reason
  |
  v
Validate JSON output
  |
  v
Upsert Signal ke Supabase (table: market_signals)
  |
  v
Dashboard Vercel akan auto-update senarai signal
  |
  v
Sleep sekejap dan ulang loop</pre>"""
html_content = re.sub(diagram_old, diagram_new, html_content, flags=re.DOTALL)

# 4. Update the Active Trade Management Section
section_3_old = r'<div class="section-head">\s*<h2>3\. Active Trade Management.*?</div>\s*</section>'
section_3_new = """<div class="section-head">
        <h2>3. Signal Management & Multi-Style</h2>
        <p>Sistem kini membolehkan beberapa style trade (Scalping, Intraday, Swing) berjalan dan memegang signal serentak dalam pangkalan data.</p>
      </div>

      <div class="cards" style="margin-top: 16px;">
        <div class="card">
          <span class="tag blue">Composite Key</span>
          <h3>Supabase Primary Key</h3>
          <p>Signal kini disimpan berdasarkan <code>(symbol, trade_style)</code> di dalam table <code>market_signals</code>. Ini mengelakkan conflict antara signal Scalping dan Swing.</p>
        </div>
        <div class="card">
          <span class="tag">Entry Zones</span>
          <h3>Zon Bukan Price Mati</h3>
          <p>AI memulangkan <code>entry_zone</code> (cth: 2340.00-2342.00) dan bukannya entry price tetap, supaya execution lebih realistik dan fleksibel.</p>
        </div>
        <div class="card">
          <span class="tag">Forced Style</span>
          <h3>AI Tidak Keliru</h3>
          <p>AI tidak lagi perlu memilih style mana. Prompt AI disuntik dengan arahan khusus untuk menilai setup "hanya untuk SCALPING" pada cycle 10 minit tersebut.</p>
        </div>
      </div>
    </section>"""
html_content = re.sub(section_3_old, section_3_new, html_content, flags=re.DOTALL)

# 5. Replace section 4 completely
section_4_old = r'<div class="section-head">\s*<h2>4\. Realtime Pattern Usage Dashboard.*?</pre>\s*<div class="callout"[^>]*>.*?</div>\s*</section>'
section_4_new = """<div class="section-head">
        <h2>4. Realtime Dashboard Vercel</h2>
        <p>Dashboard memaparkan signal yang dijana oleh Master Analyzer mengikut style secara realtime.</p>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Style</th>
              <th>Action</th>
              <th>Entry Zone</th>
              <th>SL</th>
              <th>TP</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>26 May 2026 08:26 AM</td>
              <td>SCALPING</td>
              <td><span class="pill">BUY</span></td>
              <td>2340.50 - 2342.00</td>
              <td>2338.00</td>
              <td>2345.00</td>
              <td>Liquidity Sweep + Bullish FVG</td>
            </tr>
            <tr>
              <td>26 May 2026 09:05 AM</td>
              <td>INTRADAY</td>
              <td><span class="pill">SELL</span></td>
              <td>2350.00 - 2352.00</td>
              <td>2355.00</td>
              <td>2340.00</td>
              <td>H4 Resistance + Bearish Divergence</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>"""
html_content = re.sub(section_4_old, section_4_new, html_content, flags=re.DOTALL)

# 6. Update File Yang Berperanan section
section_8_old = r'<div class="section-head">\s*<h2>8\. File Yang Berperanan.*?</div>\s*</section>'
section_8_new = """<div class="section-head">
        <h2>8. File Yang Berperanan</h2>
        <p>Ringkasan senarai fail paling latest bagi arsitektur Master Analyzer.</p>
      </div>

      <div class="cards">
        <div class="card">
          <h3><code>master_analyzer.py</code></h3>
          <p>Bot utama yang looping mengikut interval 10m/30m/60m. Baca MT5, apply logic, call AI, update Supabase market_signals.</p>
        </div>
        <div class="card">
          <h3><code>ai_engine.py</code></h3>
          <p>Membina prompt dengan memasukkan <code>forced_style</code>, memanggil API OpenRouter, dan extract JSON <code>entry_zone</code>, <code>sl_price</code>, <code>tp_price</code>.</p>
        </div>
        <div class="card">
          <h3><code>supabase_sync.py</code></h3>
          <p>Fungsi <code>upsert_market_signal</code> guna <code>conflict="symbol,trade_style"</code> supaya Supabase dapat update setiap signal mengikut stylenya.</p>
        </div>
        <div class="card">
          <h3><code>xauusd_pattern_engine.py</code></h3>
          <p>Module untuk mengesan setup dan pattern untuk XAUUSD sahaja.</p>
        </div>
        <div class="card">
          <h3><code>Dashboard/index.html</code></h3>
          <p>Paparan Vercel yang telah dimodifikasi untuk table signal baharu (tanpa symbol kerana 100% fokus XAUUSD).</p>
        </div>
      </div>
    </section>"""
html_content = re.sub(section_8_old, section_8_new, html_content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print("HTML Replaced Successfully.")
