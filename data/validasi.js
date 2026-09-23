const path = require('path');
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

async function main() {
    const jumlahSupplier = await prisma.supplier.count();
    const jumlahProduk = await prisma.produk.count();
    const jumlahPenjualan = await prisma.penjualan.count();
    const jumlahDetail = await prisma.detail_penjualan.count();

    const semuaPenjualan = await prisma.penjualan.findMany({ orderBy: { tanggal: 'asc' } });
    const tglAwal = semuaPenjualan[0]?.tanggal.toISOString().slice(0, 10);
    const tglAkhir = semuaPenjualan[semuaPenjualan.length - 1]?.tanggal.toISOString().slice(0, 10);

    console.log('=================================');
    console.log('  ANGKA FINAL DATASET (buat paper)');
    console.log('=================================');
    console.log('Periode data   :', tglAwal, 's/d', tglAkhir);
    console.log('Jumlah supplier :', jumlahSupplier);
    console.log('Jumlah produk   :', jumlahProduk);
    console.log('Header penjualan:', jumlahPenjualan);
    console.log('Detail transaksi:', jumlahDetail);
    console.log('=================================');

    // total qty per produk
    console.log('\nTotal qty terjual per produk:');
    const produkList = await prisma.produk.findMany({ orderBy: { id: 'asc' } });
    for (const produk of produkList) {
        const agg = await prisma.detail_penjualan.aggregate({
            where: { produk_id: produk.id },
            _sum: { qty: true },
        });
        console.log(`  ${produk.kode} - ${produk.nama}: ${agg._sum.qty || 0}`);
    }
}

main()
    .catch((e) => { console.error('ERROR validasi:', e); process.exit(1); })
    .finally(() => prisma.$disconnect());