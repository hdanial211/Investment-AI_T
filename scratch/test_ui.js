const puppeteer = require('puppeteer');

(async () => {
  console.log("Menghidupkan AI Agent Browser (Puppeteer)...");
  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  
  console.log("Membuka Dashboard (http://localhost:8080)...");
  await page.goto('http://localhost:8080', { waitUntil: 'networkidle0' });
  
  // Wait for Supabase to fetch accounts
  await new Promise(r => setTimeout(r, 2000));
  
  console.log("Mencari Dropdown GlobalAccountFilter...");
  const dropdownValue = await page.$eval('#globalAccountFilter', el => el.value);
  console.log("Nilai asal dropdown: " + dropdownValue);
  
  console.log("Memilih akaun Hakim (acc_2)...");
  await page.select('#globalAccountFilter', 'acc_2');
  
  // Wait for refresh to trigger and fetch data
  await new Promise(r => setTimeout(r, 2000));
  
  const selectedValue = await page.$eval('#globalAccountFilter', el => el.value);
  console.log("Nilai dropdown selepas dipilih: " + selectedValue);
  
  console.log("Menyemak jadual Active Trades...");
  const activeRows = await page.$$eval('#activeRows tr', rows => rows.map(r => r.innerText.trim()));
  
  console.log("Jumlah Active Trades untuk Hakim: " + (activeRows[0] === "-" ? 0 : activeRows.length));
  if (activeRows.length > 0 && activeRows[0] !== "-") {
      console.log("Contoh Trade: " + activeRows[0]);
  }
  
  await browser.close();
  console.log("Ujian AI selesai dengan jayanya!");
})();
