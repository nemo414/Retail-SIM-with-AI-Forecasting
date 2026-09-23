const { PrismaMariaDb } = require('@prisma/adapter-mariadb');
const { PrismaClient } = require('@prisma/client');
const bcrypt = require('bcrypt');

const adapter = new PrismaMariaDb({
    host: 'localhost',
    port: 3306,
    user: 'root',
    password: 'root',
    database: 'sim_ritel',
});
const prisma = new PrismaClient({ adapter });

async function main() {
    const jumlahUser = await prisma.users.count();
    if (jumlahUser > 0) {
        console.log('User sudah ada, seed dilewati.');
        return;
    }

    const passwordAdmin = await bcrypt.hash('admin123', 10);
    const passwordKasir = await bcrypt.hash('kasir123', 10);

    await prisma.users.create({
        data: { nama: 'Admin Toko', username: 'admin', password_hash: passwordAdmin, role: 'admin' },
    });
    await prisma.users.create({
        data: { nama: 'Kasir Toko', username: 'kasir', password_hash: passwordKasir, role: 'kasir' },
    });
    console.log('Seed user selesai: admin & kasir dibuat.');
}

main()
    .catch((e) => { console.error('ERROR seed:', e); process.exit(1); })
    .finally(() => prisma.$disconnect());