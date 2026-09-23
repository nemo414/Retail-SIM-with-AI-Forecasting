const fs = require('fs');
const path = require('path');
const { parse } = require('csv-parse/sync');
const { PrismaMariaDb } = require(path.join(__dirname, '../server/node_modules/@prisma/adapter-mariadb'));
const { PrismaClient } = require(path.join(__dirname, '../server/node_modules/@prisma/client'));

const adapter = new PrismaMariaDb({
    host: 'localhost',
    port: 3306,
    user: 'root',
    password: 'root',
    database: 'sim_ritel',
});
const prisma = new PrismaClient({ adapter });

function readCSV(name) {
    const content = fs.readFileSync(path.join(__dirname, name));
    return parse(content, { columns: true, skip_empty_lines: true });
}

async function importSupplier() {
    const rows = readCSV('master_supplier.csv');
    for (const row of rows) {
        await prisma.supplier.create({
            data: { nama: row.nama_supplier, kontak: row.kontak, alamat: row.alamat },
        });
    }
    console.log('Supplier terimport:', rows.length, 'baris');
}

async function importProduk() {
    const rows = readCSV('master_produk.csv');
    for (const row of rows) {
        await prisma.produk.create({
            data: {
                kode: row.kode,
                nama: row.nama,
                kategori: row.kategori,
                satuan: row.satuan,
                harga_beli: parseInt(row.harga_beli),
                harga_jual: parseInt(row.harga_jual),
                stok: 0,
                stok_minimum: parseInt(row.stok_minimum),
                lead_time_hari: parseInt(row.lead_time_hari),
                supplier_id: parseInt(row.supplier_id),
            },
        });
    }
    console.log('Produk terimport:', rows.length, 'baris');
}

async function importTransaksi() {
    const rows = readCSV('transaksi_penjualan.csv');
    const perTanggal = {};
    for (const row of rows) {
        if (!perTanggal[row.tanggal]) perTanggal[row.tanggal] = [];
        perTanggal[row.tanggal].push(row);
    }

    let totalHeader = 0, totalDetail = 0;
    for (const tanggal of Object.keys(perTanggal)) {
        const rowsHariIni = perTanggal[tanggal];
        const totalHari = rowsHariIni.reduce((sum, r) => sum + parseInt(r.subtotal), 0);

        const header = await prisma.penjualan.create({
            data: { tanggal: new Date(tanggal), user_id: 2, total: totalHari },
        });
        totalHeader++;

        for (const r of rowsHariIni) {
            await prisma.detail_penjualan.create({
                data: {
                    penjualan_id: header.id,
                    produk_id: parseInt(r.produk_id),
                    qty: parseInt(r.qty),
                    harga: parseInt(r.harga_satuan),
                    subtotal: parseInt(r.subtotal),
                },
            });
            totalDetail++;
        }
    }
    console.log('Penjualan (header) terimport:', totalHeader, 'baris');
    console.log('Detail penjualan terimport:', totalDetail, 'baris');
}

async function main() {
    const cekProduk = await prisma.produk.count();
    if (cekProduk > 0) {
        console.log('Data sudah ada di database. Import dibatalkan agar tidak dobel.');
        console.log('Kalau mau import ulang, kosongkan dulu tabelnya.');
        return;
    }
    await importSupplier();
    await importProduk();
    await importTransaksi();
    console.log('=== SEMUA DATA BERHASIL DIIMPORT ===');
}

main()
    .catch((e) => { console.error('ERROR import:', e); process.exit(1); })
    .finally(() => prisma.$disconnect());