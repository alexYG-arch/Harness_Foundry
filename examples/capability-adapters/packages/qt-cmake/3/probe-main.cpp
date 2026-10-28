#include <QtCore/QString>
#include <QtCore/QList>
#include <QtCore/QTextStream>
int main() {
    const auto text = QString::fromUtf8("汉A🙂");
    const auto count = text.toUcs4().size();
    QTextStream(stdout) << "QtCore:" << count << Qt::endl;
    return count == 3 ? 0 : 1;
}
